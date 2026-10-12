"""Read-only file inventory diagnostics; no parsing, embedding or worker wakeup."""
from collections import Counter
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from background_process import run_background
from languages.files import SKIP_DIRS, path_exclusion


def relative_path(path):
    if not isinstance(path, str) or not 1 <= len(path) <= 4096 or '\0' in path:
        raise ValueError('path must be a workspace-relative file or directory')
    path = path.replace('\\', '/')
    if path.startswith('/') or re.match(r'^[a-zA-Z]:', path) or '..' in path.split('/'):
        raise ValueError('path must stay inside the workspace and use a relative path')
    return PurePosixPath(path).as_posix()


def published_inventory(index):
    with index.condition:
        generation = index.generation
    if generation is not None:
        return generation.snapshot, generation.info, True
    pointer = index.state/'current.json'
    # A publishing worker may remove the old folder between these reads.
    for attempt in range(3):
        try:
            before = pointer.read_text()
            name = json.loads(before)['directory']
            if name != Path(name).name or not name.startswith('generation-'):
                break
            folder = index.state/name
            info = json.loads((folder/'metadata.json').read_text())
            files = json.loads((folder/'files.json').read_text())
            snapshot = {'files': [{'path': f['path'], 'sha256': f['sha256']} for f in files],
                        'languageOptions': index.options}
            if pointer.read_text() == before:
                return snapshot, info, True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {'files': [], 'languageOptions': index.options}, None, not pointer.exists()


def target_exclusion(index, path, discovery):
    target = index.root/path
    # Check every component without following symlinks into another directory.
    candidate = index.root
    for part in PurePosixPath(path).parts:
        candidate = candidate/part
        if candidate.is_symlink():
            return 'symlink'
    if set(PurePosixPath(path).parts) & SKIP_DIRS:
        return 'dependency-or-build-directory'
    reason = path_exclusion(path)
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in index.exclude):
        reason = 'configured-exclusion'
    if reason:
        return reason
    if discovery == 'git-tracked-and-unignored':
        ignored = run_background(['git', '-C', str(index.root), 'check-ignore', '-q', '--', path],
                                 capture_output=True)
        if ignored.returncode == 0:
            return 'git-ignored'
    if target.exists() and not target.is_file() and not target.is_dir():
        return 'not-a-regular-file'
    return None


def inspect_coverage(index, path, *, limit=50, cursor=None):
    path = relative_path(path)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('limit must be an integer from 1 to 200')
    if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r'[0-9a-f]{64}:[0-9]{1,6}', cursor)):
        raise ValueError('Invalid coverage cursor')
    details = index.scan_details(fresh=True)
    snapshot, info, manifest = published_inventory(index)
    previous = {f['path']: f['sha256'] for f in snapshot['files']}
    compatible = info is not None and index.identity(snapshot) == info['identity']
    entries = {}
    for file in details['files']:
        name = file['path']
        state = 'indexed' if compatible and previous.get(name) == file['sha256'] else 'pending'
        if not manifest:
            state = 'unknown'
        entries[name] = {'path': name, 'status': state}
        if state == 'unknown':
            entries[name]['reason'] = 'file-manifest-unavailable'
    for item in details['excluded']:
        name = item['path']
        entries[name] = {'path': name, 'status': 'excluded', 'reason': item['reason']}
        if name in previous and item['reason'] == 'not-a-regular-file' and not (index.root/name).exists():
            entries[name] = {'path': name, 'status': 'deleted'}
    for name in previous.keys()-entries.keys():
        target = index.root/name
        reason = target_exclusion(index, name, details['discovery']) if target.exists() or target.is_symlink() else None
        entries[name] = {'path': name, 'status': 'excluded', 'reason': reason} if reason else {'path': name, 'status': 'deleted'}
    # Git does not enumerate ignored paths. Explain an explicitly requested path
    # without reading it or expanding ignored dependency directories.
    selected = [entry for name, entry in sorted(entries.items())
                if path == '.' or name == path or name.startswith(path+'/')]
    if not selected and path != '.':
        reason = target_exclusion(index, path, details['discovery'])
        if reason:
            selected = [{'path': path, 'status': 'excluded', 'reason': reason}]
        elif not (index.root/path).is_dir():
            selected = [{'path': path, 'status': 'not_found'}]
    identity = hashlib.sha256(json.dumps([str(index.root), path, info['identity'] if info else None, details['files'], selected],
                                         sort_keys=True).encode()).hexdigest()
    offset = 0
    if cursor is not None:
        observed, position = cursor.split(':')
        offset = int(position)
        if observed != identity:
            raise ValueError('Coverage changed; request the first page again without cursor')
        if offset > len(selected):
            raise ValueError('Invalid coverage cursor offset')
    counts = Counter(entry['status'] for entry in selected)
    current_snapshot = {'files': [{'path': f['path'], 'sha256': f['sha256']} for f in details['files']],
                        'languageOptions': index.options}
    return {'path': path, 'discovery': details['discovery'], 'manifestAvailable': manifest,
            'generationIdentity': info['identity'] if info else None,
            'synchronized': info is not None and index.identity(current_snapshot) == info['identity'],
            'summary': {state: counts[state] for state in ['indexed', 'pending', 'excluded', 'deleted', 'not_found', 'unknown']},
            'total': len(selected), 'entries': selected[offset:offset+limit],
            'nextCursor': f'{identity}:{offset+limit}' if offset+limit < len(selected) else None}

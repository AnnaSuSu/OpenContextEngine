"""Shared file eligibility for discovery and explicitly supplied snapshots."""
import hashlib
from cancellation import check
import os
import stat
import fnmatch
from pathlib import Path, PurePosixPath
import re
from background_process import run_background

MAX_BYTES = 1024 * 1024
SKIP_DIRS = frozenset({'.git', '.hg', '.svn', 'node_modules', 'vendor', '.venv', 'venv',
                       '__pycache__', 'dist', 'build', 'target', '.next', '.cache',
                       '.pilot-state', 'runs'})
SKIP_SUFFIXES = ('.min.js', '.min.css', '.map', '.pyc', '.pyo', '.so', '.dylib', '.dll',
                 '.exe', '.o', '.a', '.class', '.jar', '.wasm', '.zip', '.gz', '.tar',
                 '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.woff', '.woff2',
                 '.mp3', '.mp4', '.sqlite', '.db', '.pem', '.key')
LOCKFILES = frozenset({'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock', 'poetry.lock',
                       'uv.lock', 'Cargo.lock', 'go.sum'})
GENERATED = re.compile(r'(?im)^\s*(?://|#|/\*|\*)\s*(?:code generated\b[^\n]*do not edit|'
                       r'(?:this file (?:is|was) |@)?(?:auto[- ]?)?generated\b[^\n]*do not edit)')
BINARY_CONTROL = re.compile(rb'[\x00-\x08\x0b\x0e-\x1f]')


def path_exclusion(name):
    path = PurePosixPath(name)
    if set(path.parts[:-1]) & SKIP_DIRS:
        return 'dependency-or-build-directory'
    if path.name in LOCKFILES or name.lower().endswith(SKIP_SUFFIXES):
        return 'generated-or-non-source-name'
    if path.name == '.env' or (path.name.startswith('.env.') and path.name not in {'.env.example', '.env.sample'}):
        return 'local-environment'
    return None


def read_text(path):
    """Return decoded source or an explicit skip reason; never replace bad bytes."""
    if path.stat().st_size > MAX_BYTES:
        return None, None, 'file-too-large'
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        return None, None, 'file-too-large'
    if BINARY_CONTROL.search(raw):
        return raw, None, 'binary-content'
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw, None, 'non-utf8'
    if GENERATED.search(text[:2048]):
        return raw, None, 'generated-header'
    return raw, text, None


def discover_snapshot(root, *, cache=None, limits=None, exclude=()):
    """Use Git's ignore rules when available, otherwise a bounded directory walk."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('Source root must be a directory')
    git = run_background(['git', '-C', str(root), 'rev-parse', '--is-inside-work-tree'],
                         capture_output=True, text=True)
    excluded, files = [], []
    if git.returncode == 0 and git.stdout.strip() == 'true':
        result = run_background(['git', '-C', str(root), 'ls-files', '-c', '-o',
                                 '--exclude-standard', '-z'], capture_output=True, check=True)
        names = sorted(set(os.fsdecode(name) for name in result.stdout.split(b'\0') if name))
        discovery = 'git-tracked-and-unignored'
    else:
        names = []
        for directory, dirs, entries in os.walk(root, followlinks=False):
            for name in sorted(dirs):
                path = Path(directory)/name
                if name in SKIP_DIRS or path.is_symlink():
                    excluded.append({'path': path.relative_to(root).as_posix()+'/',
                                     'reason': 'symlink' if path.is_symlink() else 'dependency-or-build-directory'})
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not (Path(directory)/name).is_symlink()]
            names.extend((Path(directory)/name).relative_to(root).as_posix() for name in entries)
        names.sort()
        discovery = 'directory-walk'
    limits = limits or {}
    max_files, max_bytes = limits.get('files', 50000), limits.get('bytes', 256*1024*1024)
    if len(names) > limits.get('candidates', 250000):
        raise ValueError('Source candidate limit exceeded; narrow the repository root or exclusions')
    next_cache, parents = {}, {root: True}
    total_bytes = 0
    def safe_parent(path):
        if path not in parents:
            parents[path] = path.is_relative_to(root) and safe_parent(path.parent) and not path.is_symlink()
        return parents[path]
    for name in names:
        check()
        path = root/name
        reason = path_exclusion(name)
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in exclude):
            reason = 'configured-exclusion'
        if not safe_parent(path.parent):
            reason = 'symlink'
        try:
            info = path.lstat()
        except FileNotFoundError:
            excluded.append({'path': name, 'reason': 'not-a-regular-file'})
            continue
        if stat.S_ISLNK(info.st_mode):
            reason = 'symlink'
        elif not stat.S_ISREG(info.st_mode):
            reason = 'not-a-regular-file'
        if not reason:
            def signature(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            before = signature(info) if cache is not None else None
            cached = cache.get(name) if cache is not None else None
            if cached is not None and cached[0] == before:
                _, entry, reason = cached
            else:
                raw, _, reason = read_text(path)
                entry = None if reason else {'path': name, 'bytes': len(raw),
                                             'sha256': hashlib.sha256(raw).hexdigest()}
            # Do not retain bytes read across an edit. Publication and queries
            # additionally use uncached scans, independent of stat metadata.
            if cache is not None and before == signature(path.stat()):
                next_cache[name] = (before, entry, reason)
        if reason:
            excluded.append({'path': name, 'reason': reason})
        else:
            files.append(entry)
            total_bytes += entry['bytes']
            if len(files) > max_files or total_bytes > max_bytes:
                raise ValueError('Source size limit exceeded; narrow the repository root or configure exclusions')
    if cache is not None:
        cache.clear()
        cache.update(next_cache)
    return {'schemaVersion': 1, 'scope': 'eligible UTF-8 text; structural adapters where available',
            'discovery': discovery, 'files': files, 'excluded': sorted(excluded, key=lambda item: item['path'])}

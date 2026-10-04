"""Go AST bridge with a content-addressed, local-only helper build."""
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .schema import physical_lines


@lru_cache(maxsize=8)
def toolchain(binary):
    result = subprocess.run([binary, 'version'], capture_output=True, text=True, check=True, timeout=10)
    return result.stdout.strip()


def compiler():
    binary = os.environ.get('OCE_GO_BINARY') or os.environ.get('REPONERVE_GO_BINARY') or shutil.which('go')
    if not binary:
        raise RuntimeError('Go indexing requires Go 1.22+ on PATH or OCE_GO_BINARY')
    return binary, toolchain(binary)


def settings(options=None, sources=()):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-{'mode', 'modulePath', 'goos', 'goarch'}:
        raise ValueError('Go options support mode, modulePath, goos and goarch')
    result = {'mode': 'syntax', 'modulePath': 'snapshot', 'goos': 'linux', 'goarch': 'amd64', **options}
    if result['mode'] not in {'syntax', 'types'} or result['goos'] not in {'linux', 'darwin', 'windows', 'freebsd'} or result['goarch'] not in {'amd64', 'arm64', '386', 'arm'}:
        raise ValueError('Unsupported Go analysis mode or build target')
    if 'modulePath' not in options:
        for source in sources:
            if source.path == 'go.mod':
                match = re.search(r'(?m)^module\s+("[^"\n]+"|[^\s/]+(?:/[^\s]+)*)', source.text)
                if match:
                    result['modulePath'] = match[1].strip('"')
    if not isinstance(result['modulePath'], str) or not re.fullmatch(r'[A-Za-z0-9_.~/-]+', result['modulePath']) or '..' in result['modulePath'].split('/') or result['modulePath'].startswith('/'):
        raise ValueError('Invalid Go modulePath')
    return result


def parse(sources, options):
    binary, version = compiler()
    source = Path(__file__).with_name('go_ast.go')
    semantic = source.with_name('go_types.go')
    identity = hashlib.sha256(source.read_bytes()+semantic.read_bytes()+version.encode()).hexdigest()
    cache = Path(tempfile.gettempdir())/f'reponerve-go-adapter-{getattr(os, "getuid", lambda: 0)()}'
    cache.mkdir(mode=0o700, exist_ok=True)
    if cache.is_symlink() or (os.name == 'posix' and
            (cache.stat().st_uid != os.getuid() or cache.stat().st_mode & 0o077)):
        raise RuntimeError('Go parser cache must be private to the current user')
    suffix = '.exe' if sys.platform == 'win32' else ''
    executable = cache/(identity+suffix)
    if executable.is_symlink():
        raise RuntimeError('Invalid Go parser cache entry')
    if not executable.exists():
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            target = Path(directory)/('parser'+suffix)
            env = {**os.environ, 'GOENV': 'off', 'GOWORK': 'off', 'GOTOOLCHAIN': 'local',
                   'GOPROXY': 'off', 'GO111MODULE': 'off', 'CGO_ENABLED': '0', 'GOFLAGS': '',
                   'GOCACHE': str(cache/'build')}
            built = subprocess.run([binary, 'build', '-o', str(target), str(source), str(semantic)],
                                   env=env, capture_output=True, encoding='utf-8', timeout=120)
            if built.returncode:
                raise RuntimeError('Go parser build failed: '+built.stderr[:2000])
            os.replace(target, executable)
    result = subprocess.run([str(executable)], input=json.dumps({'options': options, 'files': [
        {'path': source.path, 'text': source.text} for source in sources]}),
        encoding='utf-8', capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Go adapter failed: '+result.stderr.strip()[:2000])
    return json.loads(result.stdout)


def extract(sources, max_lines=65, options=None):
    options = settings(options)
    parsed = parse(sources, options)
    units, records, targets = [], {}, defaultdict(list)
    source_by_path = {source.path: source for source in sources}
    for file in parsed['files']:
        path = file['path']
        lines = physical_lines(source_by_path[path].text)
        module = Path(path).parent.as_posix()+'::'+file['package']
        root = {'name': '', 'kind': 'module', 'start': 1, 'end': len(lines), 'decl': 0}
        owners = [root]*len(lines)
        for entry in file['entries']:
            for i in range(entry['start']-1, entry['end']):
                owners[i] = entry
        line_units = {}
        start = 1
        while start <= len(lines):
            owner = owners[start-1]
            end = start
            while end < len(lines) and owners[end] is owner:
                end += 1
            while start <= end:
                stop = min(end, start+max_lines-1)
                if stop < end:
                    boundaries = [b for b in file['boundaries']
                                  if start+max(1, max_lines//2) <= b <= stop+1 and b > start]
                    if boundaries:
                        stop = max(boundaries)-1
                value = '\n'.join(lines[start-1:stop])
                if value.strip():
                    uid = len(units)
                    symbol = f"{path}::{owner['name']}@{owner['decl']}"
                    unit = {'id': uid, 'language': 'go', 'path': path, 'module': module,
                            'name': owner['name'], 'symbol': symbol, 'kind': owner['kind'],
                            'scope': module, 'owner': None, 'start': start, 'end': stop,
                            'text': value, 'relations': [], 'edges': [], 'calls': [], 'unresolved': []}
                    units.append(unit)
                    targets[(path, owner['decl'])].append(uid)
                    for i in range(start, stop+1):
                        line_units[i] = uid
                start = stop+1
        records[path] = line_units
        if line_units:
            units[next(iter(line_units.values()))]['goAnalysis'] = {
                **options, 'selectedForTypes': file['semantic'], 'diagnostics': file['diagnostics']}
    def add(uid, others, kind, resolution):
        for target in others:
            if uid != target:
                units[uid]['relations'].append({'target': target, 'kind': kind,
                    'confidence': 1 if kind == 'same_symbol' else .9, 'resolution': resolution})
    for (path, decl), ids in targets.items():
        if decl:
            for uid in ids:
                add(uid, ids, 'same_symbol', 'syntax')
    for file in parsed['files']:
        for reference in file['references']:
            uid = records[file['path']].get(reference['line'])
            if uid is not None:
                add(uid, targets.get((reference['targetPath'], reference['targetLine']), []),
                    'references_type', reference['resolution'])
        for call in file['calls']:
            uid = records[file['path']].get(call['line'])
            if uid is None:
                continue
            units[uid]['calls'].append(call['text'])
            ids = targets.get((call.get('targetPath'), call.get('targetLine')), [])
            if ids:
                add(uid, ids, 'calls', call['resolution'])
            else:
                units[uid]['unresolved'].append({'kind': 'calls', 'text': call['text'],
                    'line': call['line'], 'reason': 'dynamic, external or not statically bound in snapshot'})
    for unit in units:
        unit['relations'] = sorted({(r['target'], r['kind']): r for r in unit['relations']}.values(),
                                   key=lambda r: (r['target'], r['kind']))
        unit['edges'] = sorted({r['target'] for r in unit['relations']})
    return units

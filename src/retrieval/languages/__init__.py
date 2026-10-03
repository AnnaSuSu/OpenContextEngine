"""Snapshot-bound language adapters; downstream retrieval consumes only CodeUnit."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

from . import python, typescript, text, go
from .files import path_exclusion, read_text
from .schema import SCHEMA_VERSION, SourceFile, validate_units

ADAPTERS = {'python': python, 'typescript': typescript, 'javascript': typescript, 'go': go, 'text': text}
EXTENSIONS = {'.py': 'python', '.ts': 'typescript', '.tsx': 'typescript',
              '.mts': 'typescript', '.cts': 'typescript',
              '.go': 'go', '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript'}


def language_for(path):
    return EXTENSIONS.get(PurePosixPath(path).suffix.lower(), 'text')


def adapter_manifest(files, language_options=None):
    languages = sorted({language_for(file['path']) for file in files})
    options = language_options or {}
    if not isinstance(options, dict) or set(options) - set(ADAPTERS):
        raise ValueError('Unknown language options')
    paths = [Path(__file__), Path(__file__).with_name('schema.py'), Path(__file__).with_name('files.py')]
    for language in languages:
        paths.append(Path(ADAPTERS[language].__file__))
        if language in {'typescript', 'javascript'}:
            paths.append(Path(typescript.__file__).with_suffix('.mjs'))
        if language == 'go':
            paths.append(Path(go.__file__).with_name('go_ast.go'))
            paths.append(Path(go.__file__).with_name('go_types.go'))
    return {'schemaVersion': SCHEMA_VERSION, 'languages': languages, 'options': options,
            'parsers': {language: (f'python-ast-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
                                  if language == 'python' else f'typescript-{typescript.COMPILER_VERSION}'
                                  if language in {'typescript', 'javascript'} else go.compiler()[1]
                                  if language == 'go' else text.VERSION)
                        for language in languages},
            'sourceSha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}


def source_units(root, files, max_lines=65, language_options=None, report=None, cache=None):
    if type(max_lines) is not int or max_lines < 1:
        raise ValueError('max_lines must be a positive integer')
    root = Path(root).resolve()
    groups, sources, seen, excluded = defaultdict(list), [], set(), []
    options = language_options or {}
    adapter_manifest(files, options)  # Validate configuration before reading source.
    for file in files:
        name = file['path']
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or str(path) != name
                or name in seen):
            raise ValueError('Invalid or duplicate snapshot path: ' + name)
        seen.add(name)
        resolved = (root/name).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError('Source escapes snapshot root: ' + name)
        reason = path_exclusion(name)
        if (root/name).is_symlink():
            reason = 'symlink'
        if reason:
            excluded.append({'path': name, 'reason': reason})
            continue
        raw, content, reason = read_text(resolved)
        if reason:
            excluded.append({'path': name, 'reason': reason})
            continue
        if hashlib.sha256(raw).hexdigest() != file['sha256']:
            raise ValueError('Source changed: ' + name)
        source = SourceFile(name, content, file['sha256'])
        sources.append(source)
        language = language_for(name)
        groups['typescript' if language == 'javascript' else language].append(source)
    by_path = defaultdict(list)
    identities = {}
    pending_cache = {}
    for language, subset in groups.items():
        settings = options.get(language)
        if language == 'go':
            settings = go.settings(settings, sources)
        if language == 'typescript' and 'javascript' in options:
            if settings is not None and settings != options['javascript']:
                raise ValueError('JavaScript and TypeScript share compiler options')
            settings = options['javascript']
        # Bound cache lifetime to the current snapshot. Structural languages are
        # invalidated together so imports and callers in unchanged files refresh.
        batches = [[source] for source in subset] if cache is not None and language == 'text' else [subset]
        units = []
        for batch in batches:
            key = (language, batch[0].path if language == 'text' else '')
            fingerprint = (hashlib.sha256(json.dumps([
                [(s.path, s.sha256) for s in batch], max_lines, settings,
                adapter_manifest([{'path': s.path} for s in batch], options),
            ], sort_keys=True).encode()).hexdigest() if cache is not None else None)
            previous = cache.get(key) if cache is not None else None
            extracted = (deepcopy(previous[1]) if previous and previous[0] == fingerprint
                         else ADAPTERS[language].extract(batch, max_lines, settings))
            if cache is not None:
                pending_cache[key] = (fingerprint, deepcopy(extracted))
            offset = len(units)
            for unit in extracted:
                unit['id'] += offset
                for relation in unit['relations']:
                    relation['target'] += offset
                unit['edges'] = [target + offset for target in unit['edges']]
            units.extend(extracted)
        validate_units(units, subset)
        for unit in units:
            by_path[unit['path']].append(unit)
            identities[id(unit)] = (language, unit['id'])
    units = [unit for source in sources for unit in by_path[source.path]]
    remap = {identities[id(unit)]: i for i, unit in enumerate(units)}
    for i, unit in enumerate(units):
        unit['id'] = i
        for relation in unit['relations']:
            relation['target'] = remap[(identities[id(unit)][0], relation['target'])]
        unit['edges'] = sorted({relation['target'] for relation in unit['relations']})
    validate_units(units, sources)
    if cache is not None:
        cache.clear()
        cache.update(pending_cache)
    if report is not None:
        report.update(inputFiles=len(files), acceptedFiles=len(sources), excluded=excluded,
                      fallbackFiles=sum(language_for(source.path) == 'text' for source in sources))
    return units

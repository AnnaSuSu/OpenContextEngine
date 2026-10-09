"""Snapshot-bound language adapters; downstream retrieval consumes only CodeUnit."""
from collections import defaultdict
from copy import deepcopy
from cancellation import check
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

from . import python, typescript, text, go
from .files import path_exclusion, read_text
from .schema import SCHEMA_VERSION, SourceFile, SourceSyntaxError, validate_units

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
    paths = [Path(__file__), Path(__file__).with_name('schema.py'), Path(__file__).with_name('files.py'),
             Path(text.__file__)]
    for language in languages:
        paths.append(Path(ADAPTERS[language].__file__))
        if language == 'python':
            paths.append(Path(python.__file__).with_name('python_calls.py'))
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


def extract_with_fallback(adapter, sources, max_lines, settings):
    try:
        return adapter.extract(sources, max_lines, settings)
    except SourceSyntaxError as error:
        diagnostics = {item['path']: item for item in error.diagnostics}
        if not diagnostics or not set(diagnostics) <= {source.path for source in sources}:
            raise ValueError('Invalid syntax diagnostic paths') from error
        # Rebuild relations using only valid source. Never preserve partial AST
        # output or let a broken module supply symbols to its healthy callers.
        valid = [source for source in sources if source.path not in diagnostics]
        units = adapter.extract(valid, max_lines, settings) if valid else []
        for source in sources:
            if source.path not in diagnostics:
                continue
            fallback = text.extract([source], max_lines)
            for unit in fallback:
                unit['id'] += len(units)
            if fallback:
                fallback[0]['parseDiagnostic'] = {**diagnostics[source.path], 'fallback': 'text'}
            units.extend(fallback)
        return units


def source_units(root, files, max_lines=65, language_options=None, report=None, cache=None, sources_cache=None):
    if type(max_lines) is not int or max_lines < 1:
        raise ValueError('max_lines must be a positive integer')
    root = Path(root).resolve()
    groups, sources, seen, excluded = defaultdict(list), [], set(), []
    options = language_options or {}
    manifest = adapter_manifest(files, options)  # Compute runtime identity once per update.
    next_sources = {}
    for file in files:
        check()
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
        source = sources_cache.get(name) if sources_cache is not None else None
        if source is None or source.sha256 != file['sha256']:
            raw, content, reason = read_text(resolved)
            if reason:
                excluded.append({'path': name, 'reason': reason})
                continue
            if hashlib.sha256(raw).hexdigest() != file['sha256']:
                raise ValueError('Source changed: ' + name)
            source = SourceFile(name, content, file['sha256'])
        next_sources[name] = source
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
            check()
            key = (language, batch[0].path if language == 'text' else '')
            fingerprint = (hashlib.sha256(json.dumps([
                [(s.path, s.sha256) for s in batch], max_lines, settings,
                manifest,
            ], sort_keys=True).encode()).hexdigest() if cache is not None else None)
            previous = cache.get(key) if cache is not None else None
            if previous and previous[0] == fingerprint:
                # Cached canonical units remain immutable; only the ID projection is copied.
                extracted = [{**unit, 'relations': [dict(r) for r in unit['relations']],
                              'edges': list(unit['edges'])} for unit in previous[1]]
                pending_cache[key] = previous
            else:
                extracted = extract_with_fallback(ADAPTERS[language], batch, max_lines, settings)
                validate_units(extracted, batch)
                if cache is not None:
                    pending_cache[key] = (fingerprint, deepcopy(extracted))
            offset = len(units)
            for unit in extracted:
                unit['id'] += offset
                for relation in unit['relations']:
                    relation['target'] += offset
                unit['edges'] = [target + offset for target in unit['edges']]
            units.extend(extracted)
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
    if cache is not None:
        cache.clear()
        cache.update(pending_cache)
    if sources_cache is not None:
        sources_cache.clear()
        sources_cache.update(next_sources)
    if report is not None:
        diagnostics = [unit['parseDiagnostic'] for unit in units if 'parseDiagnostic' in unit]
        report.update(inputFiles=len(files), acceptedFiles=len(sources), excluded=excluded,
                      fallbackFiles=len({source.path for source in sources if language_for(source.path) == 'text'}
                                        | {item['path'] for item in diagnostics}),
                      degradedFiles=len(diagnostics), parseDiagnostics=diagnostics)
    return units

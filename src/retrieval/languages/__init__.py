"""Snapshot-bound language adapters; downstream retrieval consumes only CodeUnit."""
from collections import defaultdict
import hashlib
from pathlib import Path, PurePosixPath
import sys

from . import python, typescript
from .schema import SCHEMA_VERSION, SourceFile, validate_units

ADAPTERS = {'python': python, 'typescript': typescript}
EXTENSIONS = {'.py': 'python', '.ts': 'typescript', '.tsx': 'typescript',
              '.mts': 'typescript', '.cts': 'typescript'}


def language_for(path):
    try:
        return EXTENSIONS[PurePosixPath(path).suffix.lower()]
    except KeyError:
        raise ValueError(f'Unsupported source language: {path}') from None


def adapter_manifest(files, language_options=None):
    languages = sorted({language_for(file['path']) for file in files})
    options = language_options or {}
    if not isinstance(options, dict) or set(options) - set(ADAPTERS):
        raise ValueError('Unknown language options')
    paths = [Path(__file__), Path(__file__).with_name('schema.py')]
    for language in languages:
        paths.append(Path(ADAPTERS[language].__file__))
        if language == 'typescript':
            paths.append(Path(typescript.__file__).with_suffix('.mjs'))
    return {'schemaVersion': SCHEMA_VERSION, 'languages': languages, 'options': options,
            'parsers': {language: (f'python-ast-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
                                  if language == 'python' else f'typescript-{typescript.COMPILER_VERSION}')
                        for language in languages},
            'sourceSha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}


def source_units(root, files, max_lines=65, language_options=None):
    if type(max_lines) is not int or max_lines < 1:
        raise ValueError('max_lines must be a positive integer')
    root = Path(root).resolve()
    groups, sources, seen = defaultdict(list), [], set()
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
        raw = resolved.read_bytes()
        if hashlib.sha256(raw).hexdigest() != file['sha256']:
            raise ValueError('Source changed: ' + name)
        source = SourceFile(name, raw.decode('utf-8-sig'), file['sha256'])
        sources.append(source)
        groups[language_for(name)].append(source)
    by_path = defaultdict(list)
    for language, subset in groups.items():
        units = ADAPTERS[language].extract(subset, max_lines, options.get(language))
        validate_units(units, subset)
        for unit in units:
            by_path[unit['path']].append(unit)
    units = [unit for source in sources for unit in by_path[source.path]]
    remap = {(unit['language'], unit['id']): i for i, unit in enumerate(units)}
    for i, unit in enumerate(units):
        unit['id'] = i
        for relation in unit['relations']:
            relation['target'] = remap[(unit['language'], relation['target'])]
        unit['edges'] = sorted({relation['target'] for relation in unit['relations']})
    validate_units(units, sources)
    return units

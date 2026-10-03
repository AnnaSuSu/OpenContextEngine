"""Language-neutral source units. Relations describe static evidence, not runtime proof."""
from dataclasses import dataclass
import math
from typing import TypedDict

SCHEMA_VERSION = 'source-units-v2'
RELATION_KINDS = frozenset({'calls', 'member_of', 'inherits', 'implements',
                            'same_symbol', 'imports', 'references_type'})


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    sha256: str


def physical_lines(text):
    """Match editor line numbers: CRLF/CR/LF, not Unicode paragraph separators."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return lines[:-1] if lines and not lines[-1] else lines


class Relation(TypedDict):
    target: int
    kind: str
    confidence: float
    resolution: str


class CodeUnit(TypedDict):
    id: int
    language: str
    path: str
    module: str
    name: str
    symbol: str
    kind: str
    scope: str
    owner: str | None
    start: int
    end: int
    text: str
    relations: list[Relation]
    # Compatibility projection used by the unchanged retrieval algorithms.
    edges: list[int]


def validate_units(units, sources):
    """Require lossless source coordinates, non-overlapping spans and valid graph IDs."""
    text_paths = {unit['path'] for unit in units if unit['language'] in {'text', 'javascript', 'typescript', 'go'}}
    lines = {source.path: (physical_lines(source.text) if source.path in text_paths
                          else source.text.splitlines()) for source in sources}
    covered = {path: set() for path in lines}
    for expected, unit in enumerate(units):
        if unit['id'] != expected or unit['path'] not in lines:
            raise ValueError('Invalid unit ID or source path')
        source = lines[unit['path']]
        start, end = unit['start'], unit['end']
        if not 1 <= start <= end <= len(source):
            raise ValueError('Invalid source span')
        if unit['text'] != '\n'.join(source[start-1:end]):
            raise ValueError('Source text does not match its span')
        span = set(range(start, end+1))
        if covered[unit['path']] & span:
            raise ValueError('Overlapping source spans')
        covered[unit['path']].update(span)
        if not all(isinstance(unit[key], str) and unit[key] for key in ['language', 'module', 'symbol', 'kind', 'scope']):
            raise ValueError('Missing unit identity')
        for relation in unit['relations']:
            target, confidence = relation['target'], relation['confidence']
            if (type(target) is not int or not 0 <= target < len(units) or target == expected
                    or relation['kind'] not in RELATION_KINDS or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1 or not relation['resolution']):
                raise ValueError('Invalid static relation')
        if unit['edges'] != sorted({relation['target'] for relation in unit['relations']}):
            raise ValueError('Edges must be the exact projection of typed relations')
    for path, source in lines.items():
        missing = [i for i, line in enumerate(source, 1) if line.strip() and i not in covered[path]]
        if missing:
            raise ValueError(f'Uncovered source lines: {path}: {missing[:5]}')

"""Lossless line chunks for text without a structural adapter; no inferred edges."""
from pathlib import PurePosixPath
from .schema import physical_lines

VERSION = 'line-chunks-v1'
MAX_CHARS = 1800


def extract(sources, max_lines=65, options=None):
    if options:
        raise ValueError('Text adapter does not accept language options')
    units = []
    for source in sources:
        lines = physical_lines(source.text)
        start = 0
        while start < len(lines):
            end, size = start, 0
            while end < len(lines) and end-start < max_lines:
                cost = len(lines[end])+1
                # Keep an oversized line intact so its source coordinates remain true.
                if end > start and size+cost > MAX_CHARS:
                    break
                size += cost
                end += 1
            if end < len(lines):
                boundaries = [i+1 for i in range(start+(end-start)//2, end)
                              if not lines[i].strip()]
                if boundaries:
                    end = boundaries[-1]
            snippet = '\n'.join(lines[start:end])
            if snippet.strip():
                units.append({'id': len(units), 'language': 'text', 'path': source.path,
                              'module': source.path, 'name': PurePosixPath(source.path).name,
                              'symbol': f'text:{source.path}:L{start+1}', 'kind': 'text',
                              'scope': source.path, 'owner': None,
                              'start': start+1, 'end': end, 'text': snippet,
                              'relations': [], 'edges': []})
            start = end
    return units

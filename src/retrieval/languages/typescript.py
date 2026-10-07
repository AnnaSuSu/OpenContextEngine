"""Bridge to the pinned TypeScript compiler; reads source, never executes it."""
import json
from pathlib import Path
from background_process import run_background
from .schema import SourceSyntaxError

COMPILER_VERSION = '5.9.3'


def extract(sources, max_lines=65, options=None):
    payload = {'files': [{'path': source.path, 'text': source.text} for source in sources],
               'maxLines': max_lines, 'options': options or {}}
    try:
        result = run_background(['node', str(Path(__file__).with_suffix('.mjs'))],
                                input=json.dumps(payload), encoding='utf-8', capture_output=True,
                                timeout=120, check=False)
    except FileNotFoundError as error:
        raise RuntimeError('TypeScript indexing requires Node.js and npm ci') from error
    if result.returncode:
        raise ValueError('TypeScript adapter failed: ' + result.stderr.strip()[:2000])
    output = json.loads(result.stdout)
    if output['compilerVersion'] != COMPILER_VERSION:
        raise ValueError('Unexpected TypeScript compiler version; run npm ci')
    if output.get('syntaxErrors'):
        raise SourceSyntaxError(output['syntaxErrors'])
    return output['units']

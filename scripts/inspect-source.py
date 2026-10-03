"""Build and validate source units from a frozen manifest, without model calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from languages import adapter_manifest, source_units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    raw = args.snapshot.read_bytes()
    snapshot = json.loads(raw)
    units = source_units(args.root, snapshot['files'], language_options=snapshot.get('languageOptions'))
    summary = {'files': len(snapshot['files']), 'units': len(units),
               'languages': dict(Counter(u['language'] for u in units)),
               'edges': sum(len(u['edges']) for u in units),
               'relations': dict(Counter(r['kind'] for u in units for r in u['relations'])),
               'unresolved': sum(len(u.get('unresolved', [])) for u in units),
               'elapsedMs': round((time.monotonic()-started)*1000)}
    output = {'schemaVersion': 2, 'kind': 'source-structure-inspection',
              'snapshotSha256': hashlib.sha256(raw).hexdigest(), 'summary': summary,
              'languageAdapters': adapter_manifest(snapshot['files'], snapshot.get('languageOptions')),
              'units': units}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'output': str(args.output.resolve()), **summary}))


if __name__ == '__main__':
    main()

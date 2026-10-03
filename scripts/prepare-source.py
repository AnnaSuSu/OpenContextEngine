"""Freeze eligible text files for language-neutral indexing (no model calls)."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from languages.files import discover_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.root.resolve()):
        parser.error('Write the snapshot outside the source root to avoid indexing its own output')
    snapshot = discover_snapshot(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'output': str(args.output.resolve()), 'files': len(snapshot['files']),
                      'excluded': len(snapshot['excluded']), 'discovery': snapshot['discovery']}))


if __name__ == '__main__':
    main()

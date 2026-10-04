import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'retrieval'))
from engine import Engine, build_index
from cascade import CascadeEngine
from entities import EntityEngine
from batched import BatchedEngine
from routed import RoutedEngine


config = json.loads(sys.stdin.readline())
run = Path(config['run'])
report = json.loads((run / 'report.json').read_text())
started = time.monotonic()


def save():
    report['elapsedMs'] = round((time.monotonic() - started) * 1000)
    (run / 'report.json').write_text(json.dumps(report, indent=2))


try:
    snapshot = json.loads((run / 'snapshot.json').read_text())
    plans = json.loads((run / 'plans.json').read_text())
    units, vectors, info = build_index(config['corpus'], snapshot, config['state'], config['embeddingUrl'])
    report['indexStatus'] = info
    report['indexingMs'] = info.get('indexingMs', 0) if not info.get('cacheHit') else 0
    report['stage'] = 'querying'
    save()
    initialized = time.monotonic()
    kind = {'routed': RoutedEngine, 'batched': BatchedEngine, 'entity': EntityEngine, 'cascade': CascadeEngine}.get(config.get('engine'), Engine)
    engine = kind(units, vectors, config.get('embeddingQueryUrl', config['embeddingUrl']), config['reranker'], config.get('embeddingKey', 'local-only'))
    report['initializationMs'] = round((time.monotonic() - initialized) * 1000)
    for task in plans['results']:
        raw, debug = engine.search(task['plan'])
        name = task['id'] + '.' + task['language']
        (run / (name + '.txt')).write_text(raw)
        (run / (name + '.native.json')).write_text(json.dumps(debug, indent=2))
        report['results'].append({'id': task['id'], 'language': task['language'], 'query': task['query'],
            'status': 'completed', 'rawFile': name + '.txt', 'nativeFile': name + '.native.json',
            'sha256': hashlib.sha256(raw.encode()).hexdigest(), 'elapsedMs': debug['elapsedMs'] + task['elapsedMs'],
            'retrievalMs': debug['elapsedMs'], 'planningMs': task['elapsedMs']})
        save()
        print(json.dumps({'completed': len(report['results']), 'id': task['id'], 'language': task['language'],
            'elapsedMs': debug['elapsedMs'], 'tokens': debug['tokens']}), flush=True)
    report['status'] = 'completed'
except Exception as error:
    report['status'] = 'failed'
    report['error'] = type(error).__name__ + ': ' + str(error)[:400]
    raise
finally:
    save()

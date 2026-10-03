"""Paired retrieval experiment over existing frozen indexes, without labels."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/retrieval'))
from batched import BatchedEngine
from routed import RoutedEngine

config = json.loads(sys.stdin.readline())
plan_query = runpy.run_path(str(ROOT/'scripts/retrieval-server.py'))['plan_query']
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
code = {str(path.relative_to(ROOT)): sha(path) for path in [
    ROOT/'src/retrieval/engine.py', ROOT/'src/retrieval/batched.py',
    ROOT/'src/retrieval/routed.py', ROOT/'scripts/retrieval-server.py', Path(__file__)]}
output = ROOT/'runs'/config.get('run', 'roadmap-routing-v1')
output.mkdir(parents=True, exist_ok=False)
report = {'code': code, 'results': [], 'indexes': {}}
for dataset in config['datasets']:
    name = dataset['name']
    state = Path(dataset['state'])
    units = json.loads((state/'units.json').read_text())
    vectors = np.load(state/'vectors.npy')
    args = (units, vectors, config['embeddingUrl'], config['reranker'], config['embeddingKey'])
    classes = {'reference': BatchedEngine, 'routed': RoutedEngine}
    engines = {name: classes[name](*args) for name in config.get('variants', classes)}
    query_file = Path(dataset['queries'])
    report['indexes'][name] = {'metadata': json.loads((state/'metadata.json').read_text()),
                             'unitsSha256': sha(state/'units.json'), 'queriesSha256': sha(query_file)}
    for task in json.loads(query_file.read_text())['cases']:
        for language, query in task['queries'].items():
            # Alternate variant order; no result/query/vector cache between calls.
            order = ['reference', 'routed'] if language == 'zh' else ['routed', 'reference']
            for variant in order:
                if variant not in engines:
                    continue
                raw, debug = engines[variant].search(plan_query(query), budget=4000)
                stem = f'{name}.{task["id"]}.{language}.{variant}'
                (output/(stem+'.txt')).write_text(raw)
                (output/(stem+'.json')).write_text(json.dumps(debug, ensure_ascii=False, indent=2)+'\n')
                row = {'dataset': name, 'id': task['id'], 'language': language, 'variant': variant,
                       'rawFile': stem+'.txt', 'nativeFile': stem+'.json', 'sha256': sha(output/(stem+'.txt')),
                       'elapsedMs': debug['elapsedMs'], 'pairs': sum(w['pairs'] for w in debug['waves'])}
                report['results'].append(row)
                (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
                print(json.dumps(row), flush=True)

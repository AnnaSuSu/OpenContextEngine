"""Remote model smoke run over frozen public sources; no reference answers loaded."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/retrieval'))
import engine
from batched import BatchedEngine

config = json.loads(sys.stdin.readline())
base = ROOT/'eval/text-fallback-v1'
corpus = ROOT/'.pilot-state/text-fallback-v1/corpus'
run = ROOT/'runs/text-fallback-v1'
run.mkdir(parents=True, exist_ok=True)
assert not (run/'report.json').exists(), 'Do not overwrite a completed run'
read = lambda path: json.loads(path.read_text())
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
freeze = read(base/'freeze.json')
for name in ['snapshot.json', 'queries.json', 'protocol.json']:
    assert sha(base/name) == freeze['sha256'][name], name
code = read(base/'engine-freeze.json')
for name, expected in code['sha256'].items():
    assert sha(ROOT/name) == expected, name
snapshot = read(base/'snapshot.json')
for file in snapshot['files']:
    assert sha(corpus/file['path']) == file['sha256'], file['path']

post = engine.post
index_requests = 0


def index_embedding(url, payload, *args, **kwargs):
    global index_requests
    rows = []
    for offset in range(0, len(payload['input']), 8):
        result = post(url, {**payload, 'input': payload['input'][offset:offset+8]},
                      config['embeddingKey'], **kwargs)
        rows.extend({**row, 'index': row['index']+offset} for row in result['data'])
        index_requests += 1
    return {'data': rows}


engine.post = index_embedding
units, vectors, metadata = engine.build_index(corpus, snapshot,
    ROOT/'.pilot-state/text-fallback-v1/index', config['embeddingUrl'])
engine.post = post
retrieval = BatchedEngine(units, vectors, config['embeddingUrl'], config['reranker'], config['embeddingKey'])
plan_query = runpy.run_path(str(ROOT/'scripts/retrieval-server.py'))['plan_query']
report = {'kind': 'mixed-language-smoke', 'code': code, 'freeze': freeze,
          'index': metadata, 'indexEmbeddingRequests': index_requests, 'results': []}
for task in read(base/'queries.json')['cases']:
    for language, query in task['queries'].items():
        started = time.monotonic()
        row = {'id': task['id'], 'language': language, 'sourceLanguage': task['sourceLanguage']}
        try:
            raw, debug = retrieval.search(plan_query(query), budget=4000)
            name = f"{task['id']}.{language}"
            (run/(name+'.txt')).write_text(raw)
            (run/(name+'.json')).write_text(json.dumps(debug, ensure_ascii=False, indent=2)+'\n')
            row.update(status='completed', rawFile=name+'.txt', nativeFile=name+'.json',
                       sha256=sha(run/(name+'.txt')), elapsedMs=round((time.monotonic()-started)*1000))
        except Exception as error:
            row.update(status='failed', errorType=type(error).__name__)
        report['results'].append(row)
        print(json.dumps(row), flush=True)
        (run/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'completed': len(report['results'])}), flush=True)

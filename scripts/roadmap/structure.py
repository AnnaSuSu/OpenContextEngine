"""Index source-validated prepared views and compare text/structure with fixed engines."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/retrieval'))
from engine import document, post
from batched import BatchedEngine
from routed import RoutedEngine
from languages.schema import SourceFile, validate_units

config = json.loads(sys.stdin.readline())
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read = lambda path: json.loads(path.read_text())
plan_query = runpy.run_path(str(ROOT/'scripts/retrieval-server.py'))['plan_query']
run = ROOT/'runs'/config['run']
run.mkdir(parents=True, exist_ok=False)
report = {'code': {str(p.relative_to(ROOT)): sha(p) for p in [
    ROOT/'src/retrieval/engine.py', ROOT/'src/retrieval/batched.py', ROOT/'src/retrieval/routed.py',
    ROOT/'scripts/retrieval-server.py', Path(__file__)]}, 'indexes': {}, 'results': []}
for dataset in config['datasets']:
    name = dataset['name']
    base, corpus = Path(dataset['base']), Path(dataset['corpus'])
    snapshot = read(base/'snapshot.json')
    frozen = read(base/'freeze.json')
    for file in ['snapshot.json', 'queries.json', 'protocol.json']:
        assert sha(base/file) == frozen['sha256'][file], file
    sources = []
    for file in snapshot['files']:
        path = corpus/file['path']
        assert sha(path) == file['sha256'], file['path']
        sources.append(SourceFile(file['path'], path.read_text(encoding='utf-8-sig'), file['sha256']))
    # Index-only embedding reuse by exact model input; never query caching.
    cache = {}
    if dataset.get('reuseIndex'):
        state = Path(dataset['reuseIndex'])
        matrix = np.load(state/'vectors.npy')
        cache.update((document(u), matrix[i]) for i, u in enumerate(read(state/'units.json')))
    retrievers = {}
    report['indexes'][name] = {}
    for variant in dataset.get('variants', ['text', 'structure']):
        prepared = Path(dataset['prepared'])/(variant+'-units.json')
        prepared_hash = sha(prepared)
        data = read(prepared)
        units = data['units']
        validate_units(units, sources)
        started = time.monotonic()
        docs = [document(u) for u in units]
        missing = list(dict.fromkeys(d for d in docs if d not in cache))
        requests = 0
        for offset in range(0, len(missing), 8):
            inputs = missing[offset:offset+8]
            reply = post(config['embeddingUrl']+'/embeddings', {'model': 'Qwen3-Embedding-4B', 'input': inputs}, config['embeddingKey'], timeout=300)
            rows = sorted(reply['data'], key=lambda row: row['index'])
            assert [row['index'] for row in rows] == list(range(len(inputs)))
            for doc, row in zip(inputs, rows): cache[doc] = row['embedding']
            requests += 1
            if offset % 512 == 0: print(json.dumps({'indexing': name, 'variant': variant, 'done': offset+len(inputs), 'total': len(missing)}), flush=True)
        vectors = np.asarray([cache[d] for d in docs], dtype=np.float32)
        assert vectors.shape == (len(units), 1024) and np.isfinite(vectors).all()
        state = ROOT/'.pilot-state'/config['run']/name/variant
        state.mkdir(parents=True, exist_ok=False)
        (state/'units.json').write_text(json.dumps(units))
        np.save(state/'vectors.npy', vectors)
        metadata = {'preparedSha256': prepared_hash, 'snapshotSha256': sha(base/'snapshot.json'),
            'units': len(units), 'languageUnits': dict(Counter(u['language'] for u in units)),
            'edges': sum(len(u['edges']) for u in units), 'embeddingRequests': requests,
            'reusedEmbeddingUnits': len(docs)-len(missing), 'indexingMs': round((time.monotonic()-started)*1000),
            'adapters': data['languageAdapters'], 'queryCache': False}
        (state/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
        report['indexes'][name][variant] = metadata
        kind = RoutedEngine if config.get('engine') == 'routed' else BatchedEngine
        retrievers[variant] = kind(units, vectors, config['embeddingUrl'], config['reranker'], config['embeddingKey'])
    for task in read(base/'queries.json')['cases']:
        for language, query in task['queries'].items():
            variants = list(retrievers) if language == 'zh' else list(reversed(retrievers))
            for variant in variants:
                raw, debug = retrievers[variant].search(plan_query(query), budget=4000)
                stem = f'{name}.{task["id"]}.{language}.{variant}'
                (run/(stem+'.txt')).write_text(raw)
                (run/(stem+'.json')).write_text(json.dumps(debug, ensure_ascii=False, indent=2)+'\n')
                row = {'dataset': name, 'id': task['id'], 'language': language, 'variant': variant,
                    'rawFile': stem+'.txt', 'nativeFile': stem+'.json', 'sha256': sha(run/(stem+'.txt')), 'elapsedMs': debug['elapsedMs']}
                report['results'].append(row)
                (run/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
                print(json.dumps(row), flush=True)

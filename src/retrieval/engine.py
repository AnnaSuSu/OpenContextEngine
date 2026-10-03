"""Language-neutral retrieval over snapshot-bound source units. Models are called over HTTP, never loaded.

AST spans, conservative static links, lexical/dense fusion, facet reranking and
whole-span packing are repository independent. No evaluation labels are read.
"""
from collections import Counter, defaultdict
import hashlib
import json
import math
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import tiktoken

from languages import source_units, adapter_manifest

VERSION = 'structural-units-v2'


def terms(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    return re.findall(r'[a-z][a-z0-9]+', text.lower().replace('_', ' '))


def post(url, payload, key='local-only', timeout=120):
    request = Request(url, json.dumps(payload).encode(), {
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def document(u, limit=2200):
    return ('Path: ' + u['path'] + '\nSymbol: ' + u['name'] + '\n' + u['text'])[:limit]


class Engine:
    def __init__(self, units, vectors, embed_url, reranker, embedding_key='local-only', embedding_model='Qwen3-Embedding-4B'):
        self.units, self.vectors = units, vectors
        self.embed_url, self.reranker = embed_url, reranker
        self.embedding_key = embedding_key
        self.embedding_model = embedding_model
        self.encoding = tiktoken.get_encoding('cl100k_base')
        self.postings = defaultdict(list)
        lengths = []
        for u in units:
            counts = Counter(terms((u['path'] + ' ' + u['name'] + ' ') * 3 + u['text']))
            lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self.postings[term].append((u['id'], frequency))
        self.lengths = np.asarray(lengths)
        self.average_length = max(1, self.lengths.mean())
        self.incoming = defaultdict(list)
        for u in units:
            for target in u['edges']:
                self.incoming[target].append(u['id'])
        self.costs = [len(self.encoding.encode(self.render(u))) + 2 for u in units]

    @staticmethod
    def render(u):
        # Text units preserve Unicode separators inside a physical source line.
        lines = u['text'].split('\n') if u.get('language') in {'text', 'javascript', 'typescript', 'go'} else u['text'].splitlines()
        return f"Path: {u['path']}\n" + '\n'.join(f'{i}\t{line}' for i, line in
            enumerate(lines, u['start'])) + '\n'

    def lexical(self, query):
        scores = np.zeros(len(self.units))
        for term in set(terms(query)):
            matches = self.postings.get(term, [])
            if not matches:
                continue
            ids, tf = np.asarray(matches).T
            idf = math.log(1 + (len(self.units) - len(ids) + .5) / (len(ids) + .5))
            scores[ids] += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * self.lengths[ids] / self.average_length))
        return scores

    def rerank(self, query, ids):
        if not ids:
            return {}
        data = post(self.reranker['baseUrl'] + '/rerank', {'model': self.reranker['model'],
            'query': query, 'documents': [document(self.units[i], 5000) for i in ids]}, self.reranker['apiKey'])
        if len(data['results']) != len(ids):
            raise ValueError('Incomplete rerank response')
        return {ids[r['index']]: r['relevance_score'] for r in data['results']}

    def search(self, plan, budget=4000):
        start = time.monotonic()
        facets = plan['facets']
        queries = [plan['intent']] + [f['question'] for f in facets]
        embedded = post(self.embed_url + '/embeddings', {'model': self.embedding_model,
            'input': ['Instruct: Retrieve source code implementing the requested behavior.\nQuery: ' + q for q in queries]}, self.embedding_key)
        qvectors = np.asarray([r['embedding'] for r in sorted(embedded['data'], key=lambda r: r['index'])], dtype=np.float32)
        dense = self.vectors @ qvectors.T
        pools, fused = [], defaultdict(float)
        for col, query in enumerate(queries):
            lexical = self.lexical(query + (' ' + ' '.join(facets[col-1]['terms']) if col else ''))
            local = defaultdict(float)
            for scores in (dense[:, col], lexical):
                for rank, uid in enumerate(np.argsort(-scores)[:40]):
                    if scores[uid] > 0:
                        local[int(uid)] += 1 / (30 + rank)
            pool = sorted(local, key=local.get, reverse=True)[:28]
            pools.append(pool)
            for uid, score in local.items():
                fused[uid] += score
        facet_scores = []
        for query, pool in zip(queries, pools):
            facet_scores.append(self.rerank(query, pool))
        seeds = set()
        for scores in facet_scores:
            seeds.update(sorted(scores, key=scores.get, reverse=True)[:3])
        candidates = set().union(*(set(s) for s in facet_scores))
        expanded = set()
        for uid in seeds:
            # Only statically resolved links. Dynamic receivers are not guessed.
            neighbors = self.units[uid]['edges'] + self.incoming[uid]
            expanded.update(sorted(set(neighbors), key=lambda x: fused[x], reverse=True)[:10])
        candidates.update(expanded)
        ranked = sorted(candidates, key=lambda uid: max(s.get(uid, 0) for s in facet_scores) + min(.15, fused[uid]), reverse=True)
        retained = ranked[:80]
        # Ensure graph-only discoveries get a chance in the joint rerank.
        retained = list(dict.fromkeys(retained[:64] + sorted(expanded, key=lambda x: fused[x], reverse=True)[:16]))
        overall = self.rerank(plan['intent'], retained)
        # Score newly discovered graph spans against each facet, too.
        for col, facet in enumerate(facets, 1):
            missing = [uid for uid in retained if uid not in facet_scores[col]]
            facet_scores[col].update(self.rerank(facet['question'], missing))
        covered = np.zeros(len(facets))
        selected, spent, trace = [], 0, []
        available = set(retained)
        while available:
            choices = []
            for uid in available:
                if spent + self.costs[uid] > budget:
                    continue
                values = np.asarray([s.get(uid, 0) for s in facet_scores[1:]])
                # Diminishing coverage gain keeps later stages from being crowded out.
                gain = float(np.sum(values / (1 + covered))) / len(facets)
                gain = .7 * gain + .3 * overall.get(uid, 0)
                gain /= (max(120, self.costs[uid]) / 300) ** .35
                choices.append((gain, uid, values))
            if not choices:
                break
            gain, uid, values = max(choices, key=lambda item: (item[0], -item[1]))
            if gain < .015:
                break
            available.remove(uid)
            selected.append(uid)
            spent += self.costs[uid]
            covered += values
            trace.append({'id': uid, 'overall': overall.get(uid, 0), 'facets': values.tolist(),
                          'tokens': self.costs[uid], 'gain': gain, 'graphExpanded': uid in expanded})
        raw = '\n'.join(self.render(self.units[uid]) for uid in selected)
        return raw, {'elapsedMs': round((time.monotonic()-start)*1000), 'tokens': len(self.encoding.encode(raw)),
            'candidateCount': len(candidates), 'rerankedCount': len(retained), 'expandedCount': len(expanded),
            'selected': trace, 'plan': plan}


def build_index(root, snapshot, state, embed_url):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    adapters = adapter_manifest(snapshot['files'], snapshot.get('languageOptions'))
    identity = hashlib.sha256((VERSION + json.dumps(snapshot, sort_keys=True)
                              + json.dumps(adapters, sort_keys=True)).encode()).hexdigest()
    metadata = state / 'metadata.json'
    if metadata.exists() and json.loads(metadata.read_text())['identity'] == identity:
        return json.loads((state / 'units.json').read_text()), np.load(state / 'vectors.npy'), {
            **json.loads(metadata.read_text()), 'cacheHit': True}
    start = time.monotonic()
    selection = {}
    units = source_units(root, snapshot['files'], language_options=snapshot.get('languageOptions'), report=selection)
    if not units:
        raise ValueError('No indexable nonempty source text in snapshot')
    vectors = []
    for offset in range(0, len(units), 64):
        result = post(embed_url + '/embeddings', {'model': 'Qwen3-Embedding-4B',
            'input': [document(u) for u in units[offset:offset+64]]}, timeout=300)
        rows = sorted(result['data'], key=lambda r: r['index'])
        vectors.extend(r['embedding'] for r in rows)
        if offset % 512 == 0:
            print(json.dumps({'stage': 'indexing', 'done': len(vectors), 'total': len(units)}), flush=True)
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (len(units), 1024) or not np.isfinite(matrix).all():
        raise ValueError('Invalid index vectors')
    (state / 'units.json').write_text(json.dumps(units))
    np.save(state / 'vectors.npy', matrix)
    summary = {'identity': identity, 'version': VERSION, 'units': len(units),
        'files': len(snapshot['files']), 'nonemptyFiles': len({u['path'] for u in units}),
        'selection': selection,
        'languageAdapters': adapters, 'languageUnits': dict(Counter(u['language'] for u in units)),
        'resolvedEdges': sum(len(u['edges']) for u in units), 'indexingMs': round((time.monotonic()-start)*1000), 'cacheHit': False}
    metadata.write_text(json.dumps(summary, indent=2))
    return units, matrix, summary

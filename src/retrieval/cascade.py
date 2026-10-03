"""One neural ranking stage after cheap, parallel facet/structure retrieval.

Query-independent code structure is prepared once. Query facets interact with
stored code vectors numerically; they do not trigger separate neural reranks.
Selection considers both individual spans and complete small function bundles.
"""
from collections import defaultdict
import math
import time

import numpy as np

from engine import Engine, document, post

VERSION = 'structural-cascade-v2'
POLICY = {'candidateLimit': 96, 'facetSeeds': 4, 'neighborsPerSeed': 10,
          'facetPool': 24, 'maxFunctionBudgetFraction': .45,
          'embeddingScoreTemperature': .06, 'functionCompletionFactor': 1.25}


class CascadeEngine(Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.functions = defaultdict(list)
        for u in self.units:
            if u['kind'] == 'function':
                self.functions[u['symbol']].append(u['id'])
        for group in self.functions.values():
            group.sort(key=lambda i: self.units[i]['start'])

    def recall(self, queries, dense, facets):
        pools, fused = [], defaultdict(float)
        local_scores = []
        for col, query in enumerate(queries):
            lexical = self.lexical(query + (' ' + ' '.join(facets[col-1]['terms']) if col else ''))
            local = defaultdict(float)
            for scores in (dense[:, col], lexical):
                for rank, uid in enumerate(np.argsort(-scores)[:60]):
                    if scores[uid] > 0:
                        local[int(uid)] += 1 / (30 + rank)
            pool = sorted(local, key=lambda i: (-local[i], i))[:POLICY['facetPool']]
            pools.append(pool)
            local_scores.append(local)
            for uid, score in local.items():
                # Max preserves a facet-specific specialist; mean rewards breadth.
                fused[uid] = max(fused[uid], score)
        for uid in list(fused):
            fused[uid] += .35 * sum(s.get(uid, 0) for s in local_scores) / len(queries)
        seeds = set(uid for pool in pools for uid in pool[:POLICY['facetSeeds']])
        expanded = set()
        graph_prior = defaultdict(float)
        for uid in seeds:
            neighbors = set(self.units[uid]['edges'] + self.incoming[uid])
            ranked = sorted(neighbors, key=lambda i: (-fused[i], i))[:POLICY['neighborsPerSeed']]
            for neighbor in ranked:
                expanded.add(neighbor)
                graph_prior[neighbor] = max(graph_prior[neighbor], fused[uid] * .5)
        candidates = set().union(*(set(pool) for pool in pools), expanded)
        ordered = sorted(candidates, key=lambda i: (-(fused[i] + graph_prior[i]), i))
        # Retain direct hits from every facet before applying the shared ceiling.
        protected = list(dict.fromkeys(uid for pool in pools for uid in pool[:12]))
        retained = list(dict.fromkeys(protected + ordered))[:POLICY['candidateLimit']]
        return retained, expanded, len(candidates)

    def pack(self, retained, scores, affinity, budget):
        position = {uid: i for i, uid in enumerate(retained)}
        actions = [(uid,) for uid in retained]
        for group in self.functions.values():
            if len(group) > 1 and all(uid in position for uid in group) and sum(self.costs[uid] for uid in group) <= budget * POLICY['maxFunctionBudgetFraction']:
                actions.append(tuple(group))
        relevance = np.asarray([scores[uid] for uid in retained])
        values = relevance[:, None] * (.35 + .65 * affinity)
        covered = np.zeros(affinity.shape[1])
        selected, selected_set, trace, spent = [], set(), [], 0
        while actions:
            choices = []
            for action in actions:
                fresh = [uid for uid in action if uid not in selected_set]
                cost = sum(self.costs[uid] for uid in fresh)
                if not fresh or spent + cost > budget:
                    continue
                indices = [position[uid] for uid in fresh]
                benefit = values[indices].max(axis=0)
                base = float(relevance[indices].max())
                gain = .7 * float(np.mean(benefit / (1 + covered))) + .3 * base
                if len(action) > 1:
                    gain *= POLICY['functionCompletionFactor']
                gain /= (max(120, cost) / 300) ** .35
                choices.append((gain, action, fresh, cost, benefit))
            if not choices:
                break
            gain, action, fresh, cost, benefit = max(choices, key=lambda c: (c[0], -c[2][0]))
            if gain < .015:
                break
            actions.remove(action)
            selected.extend(fresh)
            selected_set.update(fresh)
            spent += cost
            covered += benefit
            trace.append({'ids': fresh, 'functionBundle': len(action) > 1,
                          'tokens': cost, 'gain': gain, 'scores': [scores[i] for i in fresh]})
        raw = '\n'.join(self.render(self.units[uid]) for uid in selected)
        return raw, trace

    def search(self, plan, budget=4000):
        start = time.monotonic()
        facets = plan['facets']
        queries = [plan['intent']] + [f['question'] for f in facets]
        # Encode repeated intent/facet text once, without caching across requests.
        unique_queries = list(dict.fromkeys(queries))
        result = post(self.embed_url + '/embeddings', {'model': 'Qwen3-Embedding-4B',
            'input': ['Instruct: Retrieve source code implementing the requested behavior.\nQuery: ' + q for q in unique_queries]}, self.embedding_key)
        unique_vectors = [r['embedding'] for r in sorted(result['data'], key=lambda r: r['index'])]
        vectors = np.asarray([unique_vectors[unique_queries.index(q)] for q in queries], dtype=np.float32)
        embedded_at = time.monotonic()
        dense = self.vectors @ vectors.T
        retained, expanded, candidate_count = self.recall(queries, dense, facets)
        recalled_at = time.monotonic()
        reranked = post(self.reranker['baseUrl'] + '/rerank', {'model': self.reranker['model'],
            'query': plan['intent'], 'documents': [document(self.units[uid], 5000) for uid in retained]}, self.reranker['apiKey'])
        rows = reranked['results']
        if len(rows) != len(retained) or {r['index'] for r in rows} != set(range(len(retained))) or any(not math.isfinite(r['relevance_score']) or not 0 <= r['relevance_score'] <= 1 for r in rows):
            raise ValueError('Invalid rerank mapping or scores')
        scores = {retained[r['index']]: r['relevance_score'] for r in rows}
        ranked_at = time.monotonic()
        # Soft maximum relative to each facet's best candidate avoids assuming
        # cosine similarities are calibrated cross-language probabilities.
        facet_dense = dense[retained, 1:]
        affinity = np.exp(np.minimum(0, facet_dense - facet_dense.max(axis=0)) / POLICY['embeddingScoreTemperature'])
        raw, selected = self.pack(retained, scores, affinity, budget)
        finished = time.monotonic()
        return raw, {'version': VERSION, 'elapsedMs': round((finished-start)*1000),
            'tokens': len(self.encoding.encode(raw)), 'candidateCount': candidate_count,
            'rerankedCount': len(retained), 'expandedCount': len(expanded),
            'modelRequests': {'embedding': 1, 'rerank': 1}, 'queryCache': False,
            'timingMs': {'embedding': round((embedded_at-start)*1000), 'recall': round((recalled_at-embedded_at)*1000),
                'rerank': round((ranked_at-recalled_at)*1000), 'rerankModel': reranked.get('meta', {}).get('elapsed_ms'),
                'selection': round((finished-ranked_at)*1000)},
            'rerankInputTokens': reranked.get('usage', {}).get('input_tokens'),
            'candidates': [{'id': uid, 'score': scores[uid], 'path': self.units[uid]['path'],
                'start': self.units[uid]['start'], 'end': self.units[uid]['end']} for uid in retained],
            'selected': selected, 'plan': plan, 'policy': POLICY}

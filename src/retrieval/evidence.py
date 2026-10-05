"""Evidence-oriented retrieval with per-question scoring and complete snippets.

The historical engines remain available for frozen evaluations. This engine
keeps independent recall channels, scores actual subquestions, and selects
implementation evidence before supporting tests when that is what was asked.
"""
from collections import defaultdict
import math
import re
import time

import numpy as np

from engine import Engine, document, post
from reranker import rerank_pairs

VERSION = 'evidence-v1'


def source_role(unit):
    path = unit['path'].lower()
    if re.search(r'(^|/)(tests?|__tests__|fixtures)(/|$)|(^|/)test_[^/]+|[._](test|spec)\.', path):
        return 'test'
    if unit.get('language') == 'text' or re.search(r'(^|/)(docs?|examples?)/|\.(md|rst|txt)$', path):
        return 'documentation'
    return 'implementation'


def requested_role(query):
    if re.search(r'^(?:find|show|locate|list)\s+(?:the\s+)?(?:(?:unit|regression)\s+)?tests?\b|^(?:查找|找到|列出|展示).{0,5}(?:测试|用例)', query, re.I):
        return 'test'
    if re.search(r'^(?:find|show|locate|list)\s+(?:the\s+)?(?:docs?|documentation|readme)\b|^(?:查找|找到|列出|展示).{0,5}文档', query, re.I):
        return 'documentation'
    return 'implementation'


class EvidenceEngine(Engine):
    version = VERSION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.roles = [source_role(u) for u in self.units]
        self.symbols = defaultdict(list)
        self.neighbors = [set() for _ in self.units]
        self.callees = [set() for _ in self.units]
        for u in self.units:
            if u.get('name'):
                self.symbols[u['symbol']].append(u['id'])
            for relation in u.get('relations', []):
                if relation['kind'] not in {'calls', 'same_symbol', 'references_value'}:
                    continue
                target = relation['target']
                self.neighbors[u['id']].add(target)
                self.neighbors[target].add(u['id'])
                if relation['kind'] in {'calls', 'references_value'}:
                    self.callees[u['id']].add(target)

    def substance(self, uid):
        unit = self.units[uid]
        if self.roles[uid] != 'implementation':
            return 1.0
        if unit['kind'] in {'property', 'parameter', 'type', 'interface', 'type-alias'}:
            return .25
        lines = [line.strip() for line in unit['text'].splitlines() if line.strip()]
        executable = [line for line in lines if not line.startswith(
            ('//', '/*', '*', '#', 'import ', 'from ', 'export type ', '}'))]
        if not executable:
            return .1
        if unit['kind'] in {'function', 'method'}:
            return 1.0 if len(executable) >= 2 else .5
        return 1.0 if len(executable) >= 5 else .25

    def bundle(self, uid, budget):
        unit = self.units[uid]
        family = self.symbols.get(unit['symbol'], [uid]) if unit.get('name') else [uid]
        if unit['kind'] not in {'function', 'method'}:
            return [uid]
        if sum(self.costs[i] for i in family) <= max(256, budget * .4):
            return sorted(family, key=lambda i: self.units[i]['start'])
        return [uid]

    def render_selection(self, selected):
        # Coalesce only returned source; never invent lines between snippets.
        paths = {}
        for uid in selected:
            unit = self.units[uid]
            lines = paths.setdefault(unit['path'], {})
            for number, line in enumerate(unit['text'].split('\n'), unit['start']):
                lines[number] = line
        blocks = []
        for path, lines in paths.items():
            previous = None
            for number in sorted(lines):
                if previous is None or number != previous + 1:
                    blocks.append('Path: ' + path)
                blocks.append(f'{number}\t{lines[number]}')
                previous = number
            blocks.append('')
        return '\n'.join(blocks)

    def search(self, plan, budget=4000):
        started = time.monotonic()
        declarations = bool(re.search(r'\b(interface|type alias|schema)\b|类型定义|接口类型', plan['intent'], re.I))
        def substance(uid):
            if declarations and self.units[uid]['kind'] in {'type', 'interface', 'type-alias'}:
                return 1.0
            return self.substance(uid)
        intent = plan['intent']
        facets = list(dict.fromkeys(f['question'] for f in plan['facets'] if f['question'] != intent))[:4]
        queries = [intent] + [facet + '\nContext for this part of the request: ' + intent for facet in facets]
        result = post(self.embed_url + '/embeddings', {'model': self.embedding_model,
            'input': ['Instruct: Retrieve source code implementing the requested behavior.\nQuery: ' + q for q in queries]}, self.embedding_key)
        rows = sorted(result['data'], key=lambda row: row['index'])
        if [row['index'] for row in rows] != list(range(len(queries))):
            raise ValueError('Invalid query embedding indices')
        matrix = np.asarray([row['embedding'] for row in rows], dtype=np.float32)
        if matrix.shape != (len(queries), self.vectors.shape[1]) or not np.isfinite(matrix).all():
            raise ValueError('Invalid query embedding vectors')
        dense = self.vectors @ matrix.T
        candidates, recall = set(), []
        for col, query in enumerate(queries):
            channels = []
            for scores in (dense[:, col], self.lexical(query)):
                ids = [int(uid) for uid in np.argsort(-scores, kind='stable')[:40] if scores[uid] > 0]
                candidates.update(ids)
                channels.append(ids)
            recall.append(channels)
        scores, waves = {}, []

        def score(ids):
            ids = sorted(ids)
            pairs = [(q, j) for q in range(len(queries)) for j, uid in enumerate(ids) if (q, uid) not in scores]
            if not pairs:
                return
            before = time.monotonic()
            result = rerank_pairs(self.reranker, queries, [document(self.units[i], 5000) for i in ids], pairs, post)
            for row in result['results']:
                q, j = pairs[row['index']]
                scores[q, ids[j]] = row['relevance_score']
            waves.append({'pairs': len(pairs), 'requests': result['meta']['request_count'],
                          'elapsedMs': round((time.monotonic() - before) * 1000)})

        score(candidates)
        primary = requested_role(plan['intent'])
        seeds = set()
        for q in range(len(queries)):
            order = sorted(candidates, key=lambda uid: (-scores[q, uid], uid))
            seeds.update(order[:8])
            seeds.update([i for i in order if self.roles[i] == primary and substance(i) >= .5][:6])
        support = defaultdict(float)
        for uid in sorted(seeds):
            outgoing = self.callees[uid]
            neighbors = outgoing | self.neighbors[uid]
            # Shared utility callers are broad hubs, not reliable task evidence.
            if len(neighbors) > 24:
                neighbors = outgoing
            for neighbor in neighbors:
                if neighbor not in candidates:
                    confidence = max(scores[q, uid] for q in range(len(queries)))
                    support[neighbor] = max(support[neighbor], confidence / max(1, len(neighbors)))
        expanded = sorted(support, key=lambda uid: (-support[uid], uid))[:80]
        candidates.update(expanded)
        score(expanded)

        completions = {i for uid in candidates for i in self.bundle(uid, budget)} - candidates
        score(completions)
        candidates.update(completions)

        ranks = {}
        for q in range(len(queries)):
            for role in ('implementation', 'test', 'documentation'):
                order = sorted((i for i in candidates if self.roles[i] == role),
                               key=lambda uid: (-scores[q, uid], uid))
                ranks.update({(q, uid): rank for rank, uid in enumerate(order)})

        def value(q, uid):
            relevance = scores[q, uid]
            if relevance < .1:
                return 0.0
            # Rank separates saturated probability-like scores. No inverse cost
            # reward: a short test must not displace a better-ranked body.
            return (.5 * relevance + .5 * math.exp(-ranks[q, uid] / 8)) * substance(uid) * max(0.0, scores[0, uid])

        # Tests often describe behavior more explicitly than the implementation.
        # Propagate relevance only along resolved source references, bounded by
        # the test's fan-out. This is evidence support, not invented call edges.
        corroboration = defaultdict(float)
        for uid in candidates:
            if self.roles[uid] != 'test':
                continue
            targets = [i for i in self.callees[uid] if i in candidates and self.roles[i] == 'implementation']
            if not targets or len(targets) > 8:
                continue
            for q in range(len(queries)):
                if scores[q, uid] < .1:
                    continue
                strength = (.5 * scores[q, uid] + .5 * math.exp(-ranks[q, uid] / 8)) / math.sqrt(len(targets))
                for target in targets:
                    corroboration[q, target] = max(corroboration[q, target], strength)
        selected, selected_set, trace = [], set(), []
        spent = 0
        path_counts, covered = defaultdict(int), np.zeros(len(queries))
        symbol_counts = defaultdict(int)

        def choose(ids, q=None, phase='fill', limit=None):
            nonlocal spent
            choices = []
            for uid in ids:
                if uid in selected_set:
                    continue
                bundle = [uid]
                if self.roles[uid] == primary == 'implementation':
                    # A short helper explicitly referenced by the implementation
                    # is part of its explanation (for example validation paired
                    # with mutation). Keep that source evidence together.
                    references = {r['target'] for r in self.units[uid].get('relations', [])
                                  if r.get('resolution') == 'explicit-doc-reference'}
                    extras = [i for i in sorted(references) if i in candidates and i not in selected_set
                              and self.roles[i] == 'implementation' and self.costs[i] <= min(256, budget * .1) and max(scores[col, i] for col in range(len(queries))) >= .5]
                    if sum(self.costs[i] for i in extras) <= min(256, budget * .1):
                        bundle.extend(extras)
                cost = sum(self.costs[i] for i in bundle)
                if spent + cost > (budget if limit is None else limit):
                    bundle, cost = [uid], self.costs[uid]
                if spent + cost > (budget if limit is None else limit):
                    continue
                values = [value(col, uid) + .3 * corroboration[col, uid] for col in range(len(queries))]
                merit = values[q] if q is not None else max(v / (1 + covered[col]) for col, v in enumerate(values))
                merit /= 1 + .1 * path_counts[self.units[uid]['path']] + .8 * symbol_counts[self.units[uid]['symbol']]
                if merit > 0:
                    choices.append((merit, -uid, uid, bundle, cost, values))
            if not choices:
                return False
            _, _, uid, bundle, cost, values = max(choices)
            selected.extend(bundle); selected_set.update(bundle); spent += cost
            covered[:] += values
            path_counts[self.units[uid]['path']] += 1
            symbol_counts[self.units[uid]['symbol']] += 1
            trace.append({'id': uid, 'bundle': bundle, 'phase': phase, 'role': self.roles[uid], 'tokens': cost,
                          'scores': [scores[q, uid] for q in range(len(queries))]})
            return True

        primary_ids = [i for i in candidates if self.roles[i] == primary and substance(i) >= .5]
        facets = list(range(1, len(queries))) or [0]
        # Cover behavior facets before following dependencies and continuations.
        # If the requested role is unavailable, ordinary selection can still
        # return documentation or tests as useful navigation evidence.
        for _ in range(3):
            for q in facets:
                choose(primary_ids, q, 'primary', budget * .82)
        for _ in range(2):
            companions = {i for uid in selected for i in self.callees[uid]
                          if i in candidates and self.roles[i] == primary and substance(i) >= .5}
            choose(companions, phase='dependency', limit=budget * .82)
        continuations = {i for uid in selected for i in self.bundle(uid, budget)}
        while choose(continuations, phase='continuation', limit=budget * .85):
            pass
        for q in facets:
            choose(primary_ids, q, 'primary', budget * .85)
        if primary == 'implementation' and re.search(r'\btests?\b|测试|回归', plan['intent'], re.I):
            tests = [i for i in candidates if self.roles[i] == 'test']
            related = [i for i in tests if self.callees[i] & selected_set]
            for q in facets:
                choose(related or tests, q, 'support')
        while choose(candidates):
            pass
        context = self.render_selection(selected)
        tokens = len(self.encoding.encode(context))
        if tokens > budget:
            raise ValueError('Evidence packing exceeded token budget')
        return context, {'version': VERSION, 'elapsedMs': round((time.monotonic() - started) * 1000),
            'tokens': tokens, 'queryCache': False, 'candidateCount': len(candidates),
            'rerankedCount': len(candidates), 'expandedCount': len(expanded), 'queries': queries,
            'modelRequests': {'embedding': 1, 'rerank': sum(w['requests'] for w in waves)},
            'waves': waves, 'selected': trace, 'recall': recall}

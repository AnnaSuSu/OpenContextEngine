"""Retrieve and assemble source entities, retaining their constituent spans.

Each entity has multiple stored vectors (one per source span). Cheap maximum
interaction with query facets locates entities; a single neural ranking stage
scores their representative code. Static links then supply bounded evidence
completion without another model call. No task-specific symbols or labels.
"""
from collections import defaultdict
import math
import time
import numpy as np

from engine import Engine, post

VERSION = 'entity-cascade-v3'
POLICY = {'candidateEntities': 80, 'perFacetEntities': 32, 'anchorEntities': 8,
          'graphHops': 2, 'maxAssembledEntities': 128, 'maxAtomicBudgetFraction': .65,
          'facetTemperature': .06, 'documentChars': 5000}


class EntityEngine(Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        groups = defaultdict(list)
        for u in self.units:
            groups[(u['symbol'], u['kind'])].append(u['id'])
        self.entities = []
        self.unit_entity = np.zeros(len(self.units), dtype=np.int32)
        for (symbol, kind), ids in groups.items():
            eid = len(self.entities)
            ids.sort(key=lambda i: self.units[i]['start'])
            self.entities.append({'symbol': symbol, 'kind': kind, 'ids': ids,
                                  'cost': sum(self.costs[uid] for uid in ids)})
            self.unit_entity[ids] = eid
        self.links = [dict() for _ in self.entities]
        for u in self.units:
            source = int(self.unit_entity[u['id']])
            for target_unit in u['edges']:
                target = int(self.unit_entity[target_unit])
                if source == target:
                    continue
                other = self.units[target_unit]
                # Parent context is weaker than a statically resolved callee.
                forward = .45 if u['owner'] == other['symbol'] else .85
                reverse = .65 if u['owner'] == other['symbol'] else .55
                self.links[source][target] = max(self.links[source].get(target, 0), forward)
                self.links[target][source] = max(self.links[target].get(source, 0), reverse)

    def aggregate(self, unit_scores):
        shape = (len(self.entities),) + unit_scores.shape[1:]
        scores = np.full(shape, -np.inf, dtype=np.float32)
        np.maximum.at(scores, self.unit_entity, unit_scores)
        return scores

    def candidate_entities(self, queries, facets, dense):
        fused, pools = defaultdict(float), []
        for col, query in enumerate(queries):
            lex = self.aggregate(self.lexical(query + (' ' + ' '.join(facets[col-1]['terms']) if col else '')))
            local = defaultdict(float)
            for scores in [dense[:, col], lex]:
                for rank, eid in enumerate(np.argsort(-scores)[:80]):
                    if scores[eid] > 0:
                        local[int(eid)] += 1 / (30 + rank)
            ordered = sorted(local, key=lambda i: (-local[i], i))[:POLICY['perFacetEntities']]
            pools.append(ordered)
            for eid, score in local.items():
                fused[eid] = max(fused[eid], score)
        protected = list(dict.fromkeys(eid for pool in pools for eid in pool[:12]))
        available = set(eid for pool in pools for eid in pool)
        ordered = sorted(available, key=lambda i: (-fused[i], i))
        return list(dict.fromkeys(protected + ordered))[:POLICY['candidateEntities']]

    def representation(self, eid, unit_dense):
        entity = self.entities[eid]
        ids = entity['ids']
        # Long functions are represented by their strongest matching code spans,
        # not always their prefix. Every selected span remains source anchored.
        ranked = sorted(ids, key=lambda i: (-float(unit_dense[i].max()), i))
        header = self.units[ids[0]]
        parts = [f"Path: {header['path']}\nSymbol: {header['name']}\n"]
        remaining = POLICY['documentChars'] - len(parts[0])
        for uid in ranked:
            u = self.units[uid]
            value = f"Lines {u['start']}-{u['end']}:\n{u['text']}\n"
            parts.append(value[:remaining])
            remaining -= min(len(value), remaining)
            if remaining <= 0:
                break
        return ''.join(parts)

    def complete(self, candidates, scores, dense):
        expanded_scores = dict(scores)
        provenance = {}
        anchors = sorted(candidates, key=lambda i: (-scores[i], i))[:POLICY['anchorEntities']]
        frontier = {eid: scores[eid] for eid in anchors if scores[eid] >= .15}
        visited = set(frontier)
        for hop in range(POLICY['graphHops']):
            next_frontier = {}
            for source, confidence in frontier.items():
                neighbors = self.links[source]
                # Rank by semantic compatibility before following broad class links.
                ordered = sorted(neighbors, key=lambda i: (-float(dense[i].max()), i))[:16]
                for target in ordered:
                    compatibility = float(np.exp(min(0, float(dense[target].max()-dense[source].max())) / .12))
                    proposal = confidence * neighbors[target] * (.4 + .6 * compatibility)
                    if proposal > expanded_scores.get(target, 0):
                        expanded_scores[target] = proposal
                        provenance[target] = {'anchor': source, 'hop': hop+1, 'kind': 'static-relationship', 'inferredScore': proposal}
                    if target not in visited and proposal > .05:
                        next_frontier[target] = max(next_frontier.get(target, 0), proposal)
            visited.update(next_frontier)
            frontier = next_frontier
        selected = sorted(expanded_scores, key=lambda i: (-expanded_scores[i], i))[:POLICY['maxAssembledEntities']]
        return selected, expanded_scores, provenance

    def pack_entities(self, entities, scores, dense, unit_dense, budget):
        affinity = np.exp(np.minimum(0, dense[:, 1:]-dense[:, 1:].max(axis=0)) / POLICY['facetTemperature'])
        covered = np.zeros(affinity.shape[1])
        actions = []
        for eid in entities:
            entity = self.entities[eid]
            if entity['cost'] <= budget * POLICY['maxAtomicBudgetFraction']:
                actions.append((eid, tuple(entity['ids'])))
            else:
                # Oversized entities remain accessible at their original AST spans.
                actions.extend((eid, (uid,)) for uid in entity['ids'])
        spent, selected, trace = 0, [], []
        while actions:
            best = None
            for eid, ids in actions:
                cost = sum(self.costs[i] for i in ids)
                if spent+cost > budget:
                    continue
                facet = affinity[eid]
                if len(ids) == 1 and len(self.entities[eid]['ids']) > 1:
                    facet = np.exp(np.minimum(0, unit_dense[ids[0], 1:]-dense[:, 1:].max(axis=0)) / POLICY['facetTemperature'])
                value = scores[eid] * (.35 + .65 * facet)
                gain = .7 * float(np.mean(value/(1+covered))) + .3 * scores[eid]
                gain /= (max(120, cost)/300) ** .35
                choice = (gain, eid, ids, cost, value)
                if best is None or gain > best[0]:
                    best = choice
            if best is None or best[0] < .015:
                break
            gain, eid, ids, cost, value = best
            actions.remove((eid, ids))
            selected.extend(ids)
            spent += cost
            covered += value
            trace.append({'entity': eid, 'ids': list(ids), 'symbol': self.entities[eid]['symbol'],
                'tokens': cost, 'score': scores[eid], 'completeEntity': len(ids)==len(self.entities[eid]['ids'])})
        return '\n'.join(self.render(self.units[i]) for i in selected), trace

    def search(self, plan, budget=4000):
        start = time.monotonic()
        facets = plan['facets']
        queries = [plan['intent']] + [f['question'] for f in facets]
        unique = list(dict.fromkeys(queries))
        result = post(self.embed_url+'/embeddings', {'model':'Qwen3-Embedding-4B',
            'input':['Instruct: Retrieve source code implementing the requested behavior.\nQuery: '+q for q in unique]}, self.embedding_key)
        vectors = [r['embedding'] for r in sorted(result['data'],key=lambda r:r['index'])]
        embedded = time.monotonic()
        unit_dense = self.vectors @ np.asarray([vectors[unique.index(q)] for q in queries],dtype=np.float32).T
        dense = self.aggregate(unit_dense)
        candidates = self.candidate_entities(queries,facets,dense)
        documents = [self.representation(eid,unit_dense) for eid in candidates]
        recalled = time.monotonic()
        response = post(self.reranker['baseUrl']+'/rerank',{'model':self.reranker['model'],
            'query':plan['intent'],'documents':documents},self.reranker['apiKey'])
        rows = response['results']
        if len(rows)!=len(candidates) or {r['index'] for r in rows}!=set(range(len(candidates))) or any(not math.isfinite(r['relevance_score']) or not 0<=r['relevance_score']<=1 for r in rows):
            raise ValueError('Invalid rerank response')
        scores = {candidates[r['index']]:r['relevance_score'] for r in rows}
        ranked = time.monotonic()
        assembled, expanded_scores, provenance = self.complete(candidates,scores,dense)
        raw,selected = self.pack_entities(assembled,expanded_scores,dense,unit_dense,budget)
        finished = time.monotonic()
        return raw,{'version':VERSION,'elapsedMs':round((finished-start)*1000),'tokens':len(self.encoding.encode_ordinary(raw)),
            'queryCache':False,'modelRequests':{'embedding':1,'rerank':1},'candidateCount':len(candidates),
            'expandedCount':len(provenance),'assembledCount':len(assembled),'policy':POLICY,'plan':plan,
            'timingMs':{'embedding':round((embedded-start)*1000),'recall':round((recalled-embedded)*1000),
                'rerank':round((ranked-recalled)*1000),'rerankModel':response.get('meta',{}).get('elapsed_ms'),
                'selection':round((finished-ranked)*1000)},'rerankInputTokens':response.get('usage',{}).get('input_tokens'),
            'candidates':[{'entity':eid,'ids':self.entities[eid]['ids'],'symbol':self.entities[eid]['symbol'],
                'score':expanded_scores[eid],'source':'neural+graph' if eid in scores and eid in provenance else 'neural' if eid in scores else 'graph',
                'spans':[{'path':self.units[i]['path'],'start':self.units[i]['start'],'end':self.units[i]['end']} for i in self.entities[eid]['ids']]} for eid in assembled],
            'selected':selected,'provenance':provenance}

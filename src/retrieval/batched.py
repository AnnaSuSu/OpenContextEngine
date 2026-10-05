"""Compile the reference retrieval DAG into two batched neural scoring waves.

Candidate retention reserves distinct structural neighbors before neural scoring.
Scoring uses ordinary rerank calls or optional multi-query batches. Duplicate
pairs are reused only within one request. No response or cross-query cache.
"""
from collections import defaultdict
import time
import numpy as np

from engine import Engine, document, post
from reranker import rerank_pairs

VERSION = 'batched-dag-v6'


class BatchedEngine(Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.structural_neighbors = [dict() for _ in self.units]
        for unit in self.units:
            for relation in unit.get('relations', []):
                target = relation['target']
                kind = relation['kind']
                # Follow execution and snippet completeness, not broad type/import hubs.
                supported = kind in {'calls', 'same_symbol'} or (
                    kind == 'member_of' and unit['kind'] in {'function', 'method'}
                    and self.units[target]['kind'] in {'function', 'method'})
                if supported:
                    for source, neighbor in ((unit['id'], target), (target, unit['id'])):
                        edges = self.structural_neighbors[source]
                        edges[neighbor] = max(edges.get(neighbor, 0), relation['confidence'])
        self.context_bundles = self._context_bundles()

    def _context_bundles(self):
        """Keep small callable bodies and their bounded caller context together."""
        by_symbol = defaultdict(list)
        for unit in self.units:
            by_symbol[unit['symbol']].append(unit['id'])
        owners = []
        for unit in self.units:
            symbol, parent, seen = unit['symbol'], unit.get('owner'), set()
            while parent in by_symbol and parent not in seen:
                seen.add(parent)
                ancestor = self.units[by_symbol[parent][0]]
                if ancestor['kind'] not in {'function', 'method'}:
                    break
                symbol, parent = parent, ancestor.get('owner')
            owners.append(symbol)
        families = defaultdict(list)
        for uid, symbol in enumerate(owners):
            families[symbol].append(uid)
        small = {symbol: ids for symbol, ids in families.items()
                 if self.units[by_symbol[symbol][0]]['kind'] in {'function', 'method'}
                 and sum(self.costs[uid] for uid in ids) <= 256}
        callers = defaultdict(set)
        for unit in self.units:
            for relation in unit.get('relations', []):
                source, target = owners[unit['id']], owners[relation['target']]
                if relation['kind'] == 'calls' and source != target:
                    callers[target].add(source)
        bundles = []
        for unit in self.units:
            root = owners[unit['id']]
            if root not in small:
                bundles.append([unit['id']]); continue
            included, frontier = {root}, [root]
            total = sum(self.costs[uid] for uid in small[root])
            # Bounded source-only context, never a substitute for task labels.
            for _ in range(2):
                following = []
                for symbol in frontier:
                    if len(callers[symbol]) > 4:
                        continue
                    for caller in sorted(callers[symbol], key=lambda s: families[s][0]):
                        if caller in included or caller not in small:
                            continue
                        cost = sum(self.costs[uid] for uid in small[caller])
                        if total + cost <= 768:
                            total += cost; included.add(caller); following.append(caller)
                frontier = following
            bundles.append(sorted(uid for symbol in included for uid in small[symbol]))
        return bundles

    def retain_candidates(self, ranked, expanded, facet_scores, fused, limit=80, graph_slots=16):
        core = ranked[:limit - graph_slots]
        core_set = set(core)
        support = {}
        # An unscored neighbor inherits evidence from its scored anchor. Requiring
        # the neighbor's own first-wave score would discard the point of expansion.
        for anchor in core:
            score = max(scores.get(anchor, 0) for scores in facet_scores)
            neighbors = {uid: confidence for uid, confidence in self.structural_neighbors[anchor].items()
                         if uid not in core_set}
            for uid, confidence in neighbors.items():
                support[uid] = max(support.get(uid, 0), score * confidence / len(neighbors))
        novel = (set(expanded) | set(support)) - core_set
        graph = sorted(novel, key=lambda uid: (-support.get(uid, 0), -fused[uid], uid))[:graph_slots]
        retained = list(dict.fromkeys(core + graph + ranked))[:limit]
        return retained, {'core': core, 'graph': graph,
                          'novelGraphCandidates': len(novel),
                          'support': {uid: support.get(uid, 0) for uid in graph}}

    def scoring_policy(self, cache, queries, second_wave):
        return {}

    def scoring_pairs(self, requested, queries, dense, policy):
        return requested

    def pair_score(self, cache, query, uid, queries, dense, policy):
        return cache[(query, uid)]

    def search(self, plan, budget=4000):
        start = time.monotonic()
        facets = plan['facets']
        queries = [plan['intent']] + [f['question'] for f in facets]
        unique = list(dict.fromkeys(queries))
        embedded = post(self.embed_url+'/embeddings',{'model':self.embedding_model,
            'input':['Instruct: Retrieve source code implementing the requested behavior.\nQuery: '+q for q in unique]},self.embedding_key)
        vectors = [r['embedding'] for r in sorted(embedded['data'],key=lambda r:r['index'])]
        embedding_at = time.monotonic()
        dense = self.vectors @ np.asarray([vectors[unique.index(q)] for q in queries],dtype=np.float32).T
        pools, fused = [], defaultdict(float)
        for col, query in enumerate(queries):
            lexical = self.lexical(query + (' ' + ' '.join(facets[col-1]['terms']) if col else ''))
            local = defaultdict(float)
            for scores in (dense[:, col], lexical):
                for rank, uid in enumerate(np.argsort(-scores)[:40]):
                    if scores[uid] > 0:
                        local[int(uid)] += 1 / (30 + rank)
            pools.append(sorted(local,key=local.get,reverse=True)[:28])
            for uid,score in local.items():
                fused[uid] += score
        recalled_at = time.monotonic()
        pair_cache, waves = {}, []

        def rank_wave(jobs):
            requested = [(query,uid) for query,ids in jobs for uid in ids]
            policy = self.scoring_policy(pair_cache, queries, bool(waves))
            scoring = self.scoring_pairs(requested, queries, dense, policy)
            needed = list(dict.fromkeys(pair for pair in scoring if pair not in pair_cache))
            if needed:
                query_list = list(dict.fromkeys(q for q,uid in needed))
                ids = list(dict.fromkeys(uid for q,uid in needed))
                qmap = {q:i for i,q in enumerate(query_list)}
                imap = {uid:i for i,uid in enumerate(ids)}
                pairs = [(qmap[q],imap[uid]) for q,uid in needed]
                before = time.monotonic()
                data = rerank_pairs(self.reranker, query_list,
                    [document(self.units[uid],5000) for uid in ids], pairs, post)
                rows = data['results']
                for row in rows:
                    value = row['relevance_score']
                    pair_cache[needed[row['index']]] = value
                waves.append({'elapsedMs':round((time.monotonic()-before)*1000),
                    'requests':data['meta']['request_count'],
                    'modelMs':data.get('meta',{}).get('elapsed_ms'),'pairs':len(needed),
                    'reusedPairs':len(requested)-len(needed),'inputTokens':data.get('usage',{}).get('input_tokens'),
                    'maxBatchSize':data.get('meta',{}).get('max_batch_size'),
                    'batchTokenBudget':data.get('meta',{}).get('batch_token_budget'), 'scoringPolicy': policy})
            return [{uid:self.pair_score(pair_cache, query, uid, queries, dense, policy) for uid in ids} for query,ids in jobs]

        facet_scores = rank_wave(list(zip(queries,pools)))
        seeds = set()
        for scores in facet_scores:
            seeds.update(sorted(scores,key=scores.get,reverse=True)[:3])
        candidates = set().union(*(set(s) for s in facet_scores))
        expanded = set()
        for uid in seeds:
            neighbors = self.units[uid]['edges'] + self.incoming[uid]
            expanded.update(sorted(set(neighbors),key=lambda x:fused[x],reverse=True)[:10])
        candidates.update(expanded)
        ranked = sorted(candidates,key=lambda uid:max(s.get(uid,0) for s in facet_scores)+min(.15,fused[uid]),reverse=True)
        retained, retention = self.retain_candidates(ranked, expanded, facet_scores, fused)
        expanded.update(retention['graph'])
        candidates.update(retention['graph'])
        jobs = [(plan['intent'],retained)] + [(facet['question'],retained) for facet in facets]
        outputs = rank_wave(jobs)
        overall = outputs[0]
        for col,scores in enumerate(outputs[1:],1):
            facet_scores[col].update(scores)
        ranked_at = time.monotonic()
        covered = np.zeros(len(facets))
        selected, selected_set, spent, trace = [], set(), 0, []
        available = set(retained)
        while available:
            choices = []
            for uid in available:
                bundle = [item for item in self.context_bundles[uid] if item not in selected_set]
                cost = sum(self.costs[item] for item in bundle)
                if spent+cost>budget:
                    continue
                values = np.asarray([s.get(uid,0) for s in facet_scores[1:]])
                gain = float(np.sum(values/(1+covered)))/len(facets)
                gain = .7*gain+.3*overall.get(uid,0)
                gain /= (max(120,cost)/300)**.35
                choices.append((gain,uid,values,bundle,cost))
            if not choices:
                break
            gain,uid,values,bundle,cost = max(choices,key=lambda item:(item[0],-item[1]))
            if gain<getattr(self, 'min_gain', .015):
                break
            available.difference_update(bundle);selected.extend(bundle);selected_set.update(bundle)
            spent+=cost;covered+=values
            for item in bundle:
                trace.append({'id':item,'overall':overall.get(item,0),
                    'facets':[s.get(item,0) for s in facet_scores[1:]],
                    'tokens':self.costs[item],'gain':gain,'graphExpanded':item in expanded,
                    'selectionAnchor':uid,'contextOnly':item not in retained})
        raw = '\n'.join(self.render(self.units[uid]) for uid in selected)
        end = time.monotonic()
        return raw,{'version':getattr(self, 'version', VERSION),'elapsedMs':round((end-start)*1000),'tokens':len(self.encoding.encode_ordinary(raw)),
            'candidateCount':len(candidates),'rerankedCount':len(retained),'expandedCount':len(expanded),
            'retention':retention,
            'modelRequests':{'embedding':1,'rerank':sum(w['requests'] for w in waves)},
            'rerankApi':self.reranker.get('api','rerank'),'queryCache':False,'pairCacheScope':'one-search-only',
            'waves':waves,'timingMs':{'embedding':round((embedding_at-start)*1000),'recall':round((recalled_at-embedding_at)*1000),
                'rerank':sum(w['elapsedMs'] for w in waves),'rerankModel':sum(w['modelMs'] or 0 for w in waves),
                'graphAndBookkeeping':round((ranked_at-recalled_at)*1000)-sum(w['elapsedMs'] for w in waves),
                'selection':round((end-ranked_at)*1000)},'selected':trace,'plan':plan}

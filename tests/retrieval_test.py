import hashlib
from collections import defaultdict
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'retrieval'))
from engine import source_units
from cascade import CascadeEngine
from engine import Engine, build_index
from batched import BatchedEngine


class StructuralIndexTest(unittest.TestCase):
    def test_source_coverage_and_import_self_links(self):
        sources = {'pkg/helper.py': 'def save(value):\n    return value\n', 'pkg/main.py':
            'from .helper import save as persist\n\nclass Service:\n    """A service."""\n'
            '    def run(self, value):\n        return self.finish(value)\n'
            '    def finish(self, value):\n        return persist(value)\n'}
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, text in sources.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                files.append({'path': name, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
            units = source_units(tmp, files, max_lines=5)
        for name, text in sources.items():
            covered = []
            for u in units:
                if u['path'] == name:
                    self.assertEqual(u['text'], '\n'.join(text.splitlines()[u['start']-1:u['end']]))
                    covered.extend(range(u['start'], u['end']+1))
            self.assertEqual(len(covered), len(set(covered)))
            self.assertTrue(all(i in covered for i, line in enumerate(text.splitlines(), 1) if line.strip()))
        by_name = {u['symbol']: u for u in units if u['kind'] == 'function'}
        self.assertIn(by_name['pkg.main.Service.finish']['id'], by_name['pkg.main.Service.run']['edges'])
        self.assertIn(by_name['pkg.helper.save']['id'], by_name['pkg.main.Service.finish']['edges'])

    def test_long_function_is_lossless_and_dynamic_receiver_is_not_guessed(self):
        text = 'def run(client):\n' + ''.join(f'    value_{i} = {i}\n' for i in range(30)) + '    client.save()\n\ndef save():\n    pass\n'
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'mod.py').write_text(text)
            units = source_units(tmp, [{'path': 'mod.py', 'sha256': hashlib.sha256(text.encode()).hexdigest()}], max_lines=8)
        runs = [u for u in units if u['name'] == 'run']
        self.assertGreater(len(runs), 1)
        self.assertTrue(all(u['end'] - u['start'] < 8 for u in units))
        actual = '\n'.join(u['text'] for u in runs)
        self.assertEqual(actual, '\n'.join(text.splitlines()[:32]))
        saved = next(u['id'] for u in units if u['name'] == 'save')
        self.assertTrue(all(saved not in u['edges'] for u in runs))
        self.assertTrue(all(any(v['id'] in u['edges'] for v in runs if v is not u) for u in runs))


class CascadeTest(unittest.TestCase):
    def retention_engine(self):
        units = [{'id': i, 'path': 'service.py', 'name': f'node_{i}', 'symbol': f'node_{i}',
                  'kind': 'function', 'text': f'def node_{i}(): return {i}', 'start': i+1,
                  'end': i+1, 'edges': [], 'relations': [], 'owner': None} for i in range(120)]
        return units

    def make_retention_engine(self, units):
        return BatchedEngine(units, np.zeros((len(units), 3)), 'http://unused',
                             {'baseUrl': 'http://unused', 'model': 'test', 'apiKey': 'test'})

    def test_graph_slots_are_distinct_and_unscored_neighbors_reach_second_wave(self):
        engine = self.make_retention_engine(self.retention_engine())
        ranked = list(range(96))
        expanded = set(range(16)) | set(range(96, 112))
        fused = defaultdict(float, {uid: 1 for uid in range(16)})
        retained, trace = engine.retain_candidates(ranked, expanded, [{i: .9 for i in range(64)}], fused)
        self.assertEqual(len(retained), 80)
        self.assertEqual(len(set(retained)), 80)
        self.assertTrue(set(range(96, 112)).issubset(retained))
        self.assertFalse(set(trace['core']) & set(trace['graph']))

    def test_scored_anchor_rescues_callers_and_nested_code_without_type_hubs(self):
        units = self.retention_engine()
        units[100]['relations'] = [{'target': 0, 'kind': 'calls', 'confidence': .9}]
        units[101]['kind'] = 'method'
        units[101]['relations'] = [{'target': 0, 'kind': 'member_of', 'confidence': 1}]
        units[102]['relations'] = [{'target': 0, 'kind': 'references_type', 'confidence': 1}]
        engine = self.make_retention_engine(units)
        retained, trace = engine.retain_candidates(list(range(96)), set(range(16)),
            [{0: .9}], defaultdict(float))
        self.assertIn(100, retained)
        self.assertIn(101, retained)
        self.assertNotIn(102, retained)
        self.assertGreater(trace['support'][100], 0)
        self.assertEqual(retained[:64], list(range(64)))

    def test_unused_graph_slots_backfill_existing_candidates_without_duplicates(self):
        engine = self.make_retention_engine(self.retention_engine())
        retained, trace = engine.retain_candidates(list(range(100)), set(range(10)),
            [{0: .9}], defaultdict(float))
        self.assertEqual(retained, list(range(80)))
        self.assertEqual(trace['graph'], [])

    def test_small_callable_context_keeps_nested_code_and_two_caller_hops(self):
        units = self.retention_engine()
        units[4]['owner'] = units[0]['symbol']
        units[4]['kind'] = 'method'
        for caller, callee in [(1, 0), (2, 1), (3, 2)]:
            units[caller]['relations'] = [{'target': callee, 'kind': 'calls', 'confidence': .9}]
        engine = self.make_retention_engine(units)
        self.assertEqual(engine.context_bundles[0], [0, 1, 2, 4])
        self.assertEqual(engine.context_bundles[4], [0, 1, 2, 4])
        self.assertNotIn(3, engine.context_bundles[0])

    def test_context_does_not_expand_widely_shared_helpers_or_oversized_callables(self):
        units = self.retention_engine()
        for caller in range(1, 6):
            units[caller]['relations'] = [{'target': 0, 'kind': 'calls', 'confidence': .9}]
        units[10]['text'] = 'value = 123456789\n' * 100
        engine = self.make_retention_engine(units)
        self.assertEqual(engine.context_bundles[0], [0])
        self.assertEqual(engine.context_bundles[10], [10])
        self.assertTrue(all(sum(engine.costs[i] for i in bundle) <= 768
                            for uid, bundle in enumerate(engine.context_bundles) if uid != 10))

    def test_typescript_uses_shared_index_and_retriever_and_invalidates_parser_options(self):
        sources = {'store.ts': 'export function save(value: string) { return value; }\n',
                   'main.ts': 'import { save } from "./store.js";\nexport function run() { return save("record"); }\n'}
        requests = []

        def remote(url, payload, key='local-only', timeout=120):
            requests.append(payload)
            if 'input' in payload:
                return {'data': [{'index': i, 'embedding': [1.0] + [0.0]*1023}
                                 for i in range(len(payload['input']))]}
            return {'results': [{'index': i, 'query_index': q, 'document_index': d,
                                 'relevance_score': .8} for i, (q, d) in enumerate(payload['pairs'])],
                    'meta': {'elapsed_ms': 0}}

        with tempfile.TemporaryDirectory() as directory, patch('engine.post', side_effect=remote), patch('batched.post', side_effect=remote):
            root = Path(directory)/'source'; root.mkdir()
            snapshot = {'files': []}
            for name, text in sources.items():
                (root/name).write_text(text)
                snapshot['files'].append({'path': name, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
            state = Path(directory)/'index'
            units, vectors, first = build_index(root, snapshot, state, 'http://remote/v1')
            self.assertEqual(first['languageUnits'], {'typescript': len(units)})
            _, _, cached = build_index(root, snapshot, state, 'http://remote/v1')
            self.assertTrue(cached['cacheHit'])
            self.assertEqual(len(requests), 1)
            snapshot['languageOptions'] = {'typescript': {'baseUrl': '.'}}
            _, _, changed = build_index(root, snapshot, state, 'http://remote/v1')
            self.assertFalse(changed['cacheHit'])
            self.assertNotEqual(first['identity'], changed['identity'])
            retriever = BatchedEngine(units, vectors, 'http://remote/v1',
                {'baseUrl': 'http://remote/v1', 'model': 'test', 'apiKey': 'test'})
            plan = {'intent': 'save a record', 'facets': [{'question': 'save a record', 'terms': ['save']}]}
            raw, debug = retriever.search(plan, budget=200)
            self.assertIn('store.ts', raw)
            self.assertIn('export function save', raw)
            self.assertLessEqual(debug['tokens'], 200)
            self.assertFalse(debug['queryCache'])

    def test_single_rerank_preserves_response_mapping_and_never_caches_queries(self):
        units = [{'id': i, 'path': 'service.py', 'name': name, 'symbol': 'service.' + name,
            'kind': 'function', 'text': f'def {name}():\n    return {i}', 'start': 1+3*i, 'end': 2+3*i,
            'edges': [], 'owner': None} for i, name in enumerate(['store', 'load', 'format'])]
        retriever = CascadeEngine(units, np.eye(3, dtype=np.float32), 'http://remote-embedding/v1', {'baseUrl': 'http://remote-reranker/v1', 'model': 'test', 'apiKey': 'test'}, 'test')
        calls = []
        def service(url, payload, key='test', timeout=120):
            calls.append((url, payload))
            if 'input' in payload:
                return {'data': [{'index': i, 'embedding': [1, 0, 0]} for i in range(len(payload['input']))]}
            return {'results': [{'index': i, 'relevance_score': .9 if 'def load' in doc else .1}
                for i, doc in reversed(list(enumerate(payload['documents'])))], 'meta': {'elapsed_ms': 1}}
        plan = {'intent': 'load stored value', 'facets': [{'question': 'load stored value', 'terms': ['load']}]}
        with patch('cascade.post', side_effect=service):
            first, debug = retriever.search(plan, budget=100)
            second, _ = retriever.search(plan, budget=100)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 4)
        self.assertEqual(sum('documents' in p for _, p in calls), 2)
        self.assertEqual(len(calls[0][1]['input']), 1)
        self.assertLessEqual(debug['tokens'], 100)
        self.assertIn('def load', first)
        ranked_load = next(c for c in debug['candidates'] if c['start'] == 4)
        self.assertEqual(ranked_load['score'], .9)

    def test_batched_execution_matches_reference_algorithm_with_identical_pair_scores(self):
        units = [{'id':i,'path':'service.py','name':f'function_{i}','symbol':f'service.function_{i}',
            'kind':'function','text':f'def function_{i}():\n    return {i}', 'start':i*3+1,'end':i*3+2,
            'edges':[(i+1)%50,(i+7)%50],'owner':None} for i in range(50)]
        vectors = np.random.default_rng(19).normal(size=(50,16)).astype(np.float32)
        args = (units,vectors,'http://embed/v1',{'baseUrl':'http://rank/v1','model':'test','apiKey':'test'})
        reference, batched = Engine(*args), BatchedEngine(*args)
        counts = {'pairs':0,'single':0}
        def relevance(q,d):
            return int(hashlib.sha256((q+d).encode()).hexdigest()[:8],16)/0xffffffff
        def remote(url,payload,key='local-only',timeout=120):
            if 'input' in payload:
                return {'data':[{'index':i,'embedding':[.2]*16} for i in range(len(payload['input']))]}
            if 'pairs' in payload:
                counts['pairs']+=1
                return {'results':[{'index':i,'query_index':q,'document_index':d,
                    'relevance_score':relevance(payload['queries'][q],payload['documents'][d])} for i,(q,d) in reversed(list(enumerate(payload['pairs'])))], 'meta':{'elapsed_ms':0}}
            counts['single']+=1
            return {'results':[{'index':i,'relevance_score':relevance(payload['query'],d)} for i,d in enumerate(payload['documents'])]}
        plan={'intent':'persist records and read them','facets':[{'question':'persist records','terms':['persist']},{'question':'read records','terms':['read']}]}
        with patch('engine.post',side_effect=remote),patch('batched.post',side_effect=remote):
            expected,_=reference.search(plan,budget=300)
            actual,debug=batched.search(plan,budget=300)
            again,_=batched.search(plan,budget=300)
        self.assertEqual(actual,expected)
        self.assertEqual(again,expected)
        self.assertEqual(counts['pairs'],4)
        self.assertGreater(counts['single'],2)
        self.assertEqual(debug['modelRequests']['rerank'],2)


if __name__ == '__main__':
    unittest.main()

from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/retrieval'))
from reranker import rerank_pairs
from routed import RoutedEngine

CONFIG = {'baseUrl': 'https://provider.invalid/v2/', 'model': 'fixture', 'apiKey': 'test'}


class RerankerTest(unittest.TestCase):
    def test_sparse_pairs_sorted_responses_chunking_and_deduplication(self):
        calls = []
        def post(url, body, key):
            calls.append(body)
            self.assertEqual(url, 'https://provider.invalid/v2/rerank')
            self.assertEqual(key, 'test')
            self.assertEqual(body['top_n'], len(body['documents']))
            return {'results': [{'index': i, 'relevance_score': float(d)}
                                for i, d in reversed(list(enumerate(body['documents'])))]}
        pairs = [(1, 3), (0, 1), (1, 0), (1, 3), (1, 2)]
        result = rerank_pairs({**CONFIG, 'maxDocuments': 2, 'concurrency': 1},
                              ['first', 'second'], ['.1', '.2', '.3', '.4'], pairs, post)
        self.assertEqual([r['relevance_score'] for r in result['results']], [.4, .2, .1, .4, .3])
        self.assertEqual([(r['query_index'], r['document_index']) for r in result['results']], pairs)
        self.assertEqual(sum(len(c['documents']) for c in calls), 4)
        self.assertEqual(result['meta']['request_count'], 3)

    def test_concurrency_is_bounded_and_requests_can_overlap(self):
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = peak = 0
        def post(*args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=5)
            with lock:
                active -= 1
            return {'results': [{'index': 0, 'relevance_score': .5}]}
        result = rerank_pairs(CONFIG, ['a', 'b', 'c', 'd'], ['code'], [(i, 0) for i in range(4)], post)
        self.assertEqual(peak, 2)
        self.assertEqual(result['meta']['request_count'], 4)

    def test_invalid_results_fail_instead_of_assigning_scores_to_wrong_documents(self):
        valid = [{'index': 0, 'relevance_score': .5}, {'index': 1, 'relevance_score': .8}]
        invalid = [[], valid[:1], [valid[0], valid[0]], [valid[0], {'index': 2, 'relevance_score': .5}],
                   [valid[0], {'index': True, 'relevance_score': .5}]]
        invalid += [[valid[0], {'index': 1, 'relevance_score': v}]
                    for v in [float('nan'), float('inf'), -.1, 1.1, True, '.5']]
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                rerank_pairs(CONFIG, ['query'], ['a', 'b'], [(0, 0), (0, 1)],
                             lambda *args: {'results': rows})

    def test_provider_errors_are_propagated_without_api_fallback(self):
        error = HTTPError('https://provider.invalid/v2/rerank', 401, 'Unauthorized', {}, None)
        calls = []
        def post(*args):
            calls.append(args)
            raise error
        try:
            with self.assertRaises(HTTPError) as raised:
                rerank_pairs(CONFIG, ['query'], ['code'], [(0, 0)], post)
            self.assertIs(raised.exception, error)
            self.assertEqual(len(calls), 1)
        finally:
            error.close()

    def test_configuration_and_empty_work(self):
        for config in [{'api': 'auto'}, {'concurrency': 0}, {'concurrency': True}, {'maxDocuments': 0}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                rerank_pairs({**CONFIG, **config}, ['q'], ['d'], [(0, 0)], lambda *args: self.fail('Unexpected request'))
        result = rerank_pairs(CONFIG, [], [], [], lambda *args: self.fail('Unexpected request'))
        self.assertEqual(result['meta']['request_count'], 0)

    def test_standard_and_batch_preserve_retrieval_and_per_search_score_reuse(self):
        units = [{'id': i, 'path': 'store.py', 'name': f'save_{i}', 'symbol': f'save_{i}',
                  'language': 'python', 'kind': 'function', 'text': f'def save_{i}():\n    return {i}',
                  'start': i * 3 + 1, 'end': i * 3 + 2, 'owner': None, 'edges': [], 'relations': []}
                 for i in range(60)]
        plan = {'intent': 'save and retrieve', 'facets': [
            {'question': 'save', 'terms': ['save']}, {'question': 'retrieve', 'terms': ['retrieve']}]}
        for confidence in [.8, .02]:
            outcomes = []
            for api in ['rerank', 'rerank-batch']:
                seen, calls = [], []
                def post(url, body, *args):
                    if 'input' in body:
                        return {'data': [{'index': i, 'embedding': [1., 0., 0., 0.]}
                                         for i in range(len(body['input']))]}
                    calls.append(url)
                    pairs = ([(body['queries'][q], body['documents'][d]) for q, d in body['pairs']]
                             if 'pairs' in body else [(body['query'], d) for d in body['documents']])
                    seen.extend(pairs)
                    return {'results': [{'index': i, 'relevance_score': confidence if q == plan['intent'] else .8,
                            **({'query_index': body['pairs'][i][0], 'document_index': body['pairs'][i][1]}
                               if 'pairs' in body else {})} for i, (q, d) in reversed(list(enumerate(pairs)))]}
                engine = RoutedEngine(units, np.ones((60, 4), dtype=np.float32), 'https://embed.invalid/v1',
                                      {**CONFIG, 'api': api})
                with patch('batched.post', side_effect=post):
                    raw, debug = engine.search(plan, budget=1000)
                    self.assertEqual(len(seen), len(set(seen)))
                    self.assertEqual(debug['modelRequests']['rerank'], len(calls))
                    count = len(seen)
                    again, _ = engine.search(plan, budget=1000)
                    self.assertEqual(len(seen), count * 2)
                    self.assertEqual(raw, again)
                self.assertEqual(debug['rerankApi'], api)
                outcomes.append((raw, debug['selected'], debug['waves'][-1]['scoringPolicy']))
            self.assertEqual(outcomes[0], outcomes[1])


if __name__ == '__main__':
    unittest.main()

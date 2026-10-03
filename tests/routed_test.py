"""Fast scoring keeps model budgets and repairs low-confidence full questions."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from routed import RoutedEngine


class RoutedTest(unittest.TestCase):
    def engine(self):
        units = [{'id': i, 'path': 'store.py', 'name': f'save_{i}', 'symbol': f'save_{i}',
            'language': 'python', 'kind': 'function', 'text': f'def save_{i}():\n    return {i}',
            'start': i*3+1, 'end': i*3+2, 'owner': None, 'edges': [], 'relations': []} for i in range(60)]
        return RoutedEngine(units, np.ones((60, 4), dtype=np.float32), 'http://embedding/v1',
                            {'baseUrl': 'http://rerank/v1', 'model': 'test', 'apiKey': 'test'})

    def run_search(self, full_score):
        calls = []
        plan = {'intent': 'save values and retrieve records', 'facets': [
            {'question': 'save values', 'terms': ['save']},
            {'question': 'retrieve records', 'terms': ['retrieve']}]}
        def model(url, payload, *args, **kwargs):
            calls.append(payload)
            if 'input' in payload:
                return {'data': [{'index': i, 'embedding': [1., 0., 0., 0.]}
                                 for i in range(len(payload['input']))]}
            return {'results': [{'index': i, 'query_index': q, 'document_index': d,
                'relevance_score': full_score if payload['queries'][q] == plan['intent'] else .8}
                for i, (q, d) in reversed(list(enumerate(payload['pairs'])))]}
        engine = self.engine()
        with patch('batched.post', side_effect=model):
            first = engine.search(plan, budget=1000)
            again = engine.search(plan, budget=1000)
        self.assertEqual(first[0], again[0])
        self.assertEqual(sum('input' in call for call in calls), 2)
        for raw, debug in [first, again]:
            self.assertLessEqual(debug['tokens'], 1000)
            self.assertEqual(debug['modelRequests']['embedding'], 1)
            self.assertLessEqual(debug['modelRequests']['rerank'], 2)
            self.assertFalse(debug['queryCache'])
        return first, calls

    def test_high_confidence_scores_each_candidate_only_once_per_search(self):
        (raw, debug), calls = self.run_search(.8)
        self.assertTrue(raw)
        self.assertTrue(all(call['queries'] == ['save values and retrieve records'] for call in calls if 'pairs' in call))
        self.assertTrue(all(not wave['scoringPolicy']['fullFacets'] for wave in debug['waves']))

    def test_low_full_question_confidence_uses_real_facet_scores_within_two_waves(self):
        (raw, debug), calls = self.run_search(.02)
        self.assertTrue(raw)
        self.assertTrue(debug['waves'][-1]['scoringPolicy']['fullFacets'])
        self.assertTrue(any(len(call.get('queries', [])) > 1 for call in calls))
        self.assertTrue(any(max(item['facets']) == .8 for item in debug['selected']))

    def test_invalid_pair_mapping_is_rejected(self):
        engine = self.engine()
        def model(url, payload, *args, **kwargs):
            if 'input' in payload:
                return {'data': [{'index': i, 'embedding': [1., 0., 0., 0.]}
                                 for i in range(len(payload['input']))]}
            return {'results': [{'index': i, 'query_index': 99, 'document_index': d, 'relevance_score': .8}
                                for i, (_, d) in enumerate(payload['pairs'])]}
        with patch('batched.post', side_effect=model), self.assertRaisesRegex(ValueError, 'mapping'):
            engine.search({'intent': 'save', 'facets': [{'question': 'save', 'terms': []}]})

"""Behavioral regressions for evidence selection; no external model calls."""
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/retrieval'))
from evidence import EvidenceEngine


def unit(i, path, text, name=None, start=1, kind='function', relations=()):
    name = name or f'fn{i}'
    return {'id': i, 'path': path, 'name': name, 'symbol': path + '::' + name,
            'language': 'python', 'kind': kind, 'text': text, 'start': start,
            'end': start + len(text.splitlines()) - 1, 'owner': None,
            'edges': [r['target'] for r in relations], 'relations': list(relations)}


class EvidenceTest(unittest.TestCase):
    def search(self, units, query='Find implementation and tests for saving records', budget=1000, scores=None, facets=None):
        engine = EvidenceEngine(units, np.ones((len(units), 4), dtype=np.float32), 'http://embed',
                                {'baseUrl': 'http://rank', 'model': 'test', 'apiKey': 'test', 'api': 'rerank-batch'})
        calls = []
        def model(url, body, *args):
            calls.append(body)
            if 'input' in body:
                return {'data': [{'index': i, 'embedding': [1., 0., 0., 0.]} for i in range(len(body['input']))]}
            return {'results': [{'index': i, 'query_index': q, 'document_index': d,
                                 'relevance_score': scores(body['queries'][q], body['documents'][d]) if scores else .999}
                                for i, (q, d) in enumerate(body['pairs'])]}
        with patch('evidence.post', side_effect=model):
            context, debug = engine.search({'intent': query, 'facets': [{'question': f, 'terms': []} for f in (facets or [query])]}, budget)
        self.assertLessEqual(debug['tokens'], budget)
        self.assertEqual(debug['tokens'], len(engine.encoding.encode(context)))
        return context, debug, calls

    def test_long_ranked_implementation_survives_short_test_crowding(self):
        body = 'def save():\n' + ''.join(f'    result_{i} = {i}\n' for i in range(35)) + '    return result_34'
        units = [unit(0, 'app.py', body, 'save')]
        units += [unit(i, f'tests/test_{i}.py', 'def check():\n    assert save()') for i in range(1, 30)]
        context, _, _ = self.search(units, budget=550)
        self.assertIn('return result_34', context)
        self.assertIn('Path: app.py', context)

    def test_each_behavior_has_implementation_with_shared_context(self):
        units = [unit(0, 'save.py', 'def save():\n    persist()'), unit(1, 'restore.py', 'def restore():\n    rebuild()')]
        context, _, calls = self.search(units, query='Save and restore chat records', facets=['Save chat records', 'Restore chat records'])
        self.assertIn('Path: save.py', context)
        self.assertIn('Path: restore.py', context)
        self.assertTrue(all('Save and restore chat records' in q for call in calls if 'pairs' in call for q in call['queries']))

    def test_explicit_tests_and_docs_are_not_overridden_by_source_priority(self):
        units = [unit(0, 'app.py', 'def save():\n    pass'), unit(1, 'tests/test_save.py', 'def check():\n    assert save()'),
                 dict(unit(2, 'docs/save.md', 'Save guide\nUse save for records'), language='text')]
        for query, path in [('Find tests for saving records', 'tests/test_save.py'), ('Find documentation for saving records', 'docs/save.md')]:
            context, debug, _ = self.search(units, query=query, budget=100)
            self.assertEqual(units[debug['selected'][0]['id']]['path'], path)

    def test_completion_is_scored_and_lines_are_exact_without_duplicate_headers(self):
        units = [unit(0, 'app.py', 'def save():\n    first()', 'save'), unit(1, 'app.py', '    second()\n    return 1', 'save', start=3)]
        context, _, _ = self.search(units)
        self.assertEqual(context.count('Path: app.py'), 1)
        self.assertIn('1\tdef save():\n2\t    first()\n3\t    second()\n4\t    return 1', context)

    def test_disjoint_source_spans_do_not_invent_intervening_lines(self):
        units = [unit(0, 'app.py', 'def save():\n    return 1'), unit(1, 'app.py', 'def restore():\n    return 2', start=10)]
        context, _, _ = self.search(units)
        self.assertEqual(context.count('Path: app.py'), 2)
        self.assertNotRegex(context, r'\n[3-9]\t')

    def test_relevant_test_can_supply_implementation_outside_dense_top40(self):
        units = [unit(i, f'tests/test_{i}.py', 'def check():\n    assert True') for i in range(45)]
        units[0]['relations'] = [{'kind': 'calls', 'target': 44}]
        units[0]['edges'] = [44]
        units[44] = unit(44, 'app.py', 'def handler():\n    return True')
        context, debug, _ = self.search(units, query='Find implementation for the behavior')
        self.assertIn('Path: app.py', context)
        self.assertGreater(debug['expandedCount'], 0)

    def test_zero_relevance_produces_no_fabricated_evidence(self):
        context, _, _ = self.search([unit(0, 'app.py', 'def save():\n    return 1')], scores=lambda q, d: 0)
        self.assertEqual(context, '')

    def test_small_budget_does_not_truncate_source_to_fake_completion(self):
        context, _, _ = self.search([unit(0, 'app.py', 'def save():\n' + '    expensive_statement()\n' * 200)], budget=64)
        self.assertEqual(context, '')

    def test_model_pairs_are_unique_within_search(self):
        units = [unit(i, f'app{i}.py', 'def save():\n    return 1') for i in range(10)]
        _, _, calls = self.search(units, facets=['Save records', 'Restore records'])
        pairs = [(call['queries'][q], call['documents'][d]) for call in calls if 'pairs' in call for q, d in call['pairs']]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_zero_relevance_tests_do_not_promote_unrelated_dependencies(self):
        units = [unit(0, 'tests/test_save.py', 'def check():\n    save()', relations=[{'kind': 'calls', 'target': 1}]),
                 unit(1, 'app.py', 'def save():\n    return 1')]
        context, _, _ = self.search(units, scores=lambda q, d: 0)
        self.assertEqual(context, '')

    def test_short_explicit_helper_is_returned_with_implementation(self):
        units = [unit(0, 'app.py', 'def save():\n    return 1', relations=[
                 {'kind': 'references_value', 'target': 1, 'resolution': 'explicit-doc-reference'}]),
                 unit(1, 'helper.py', 'def validate():\n    return True')]
        context, debug, _ = self.search(units, scores=lambda q, d: .99 if 'Path: app.py' in d else .6)
        self.assertEqual(set(debug['selected'][0]['bundle']), {0, 1})
        self.assertIn('def validate()', context)

    def test_explicit_interface_query_can_select_declarations(self):
        units = [dict(unit(0, 'types.ts', 'export interface Response {\n  count: number;\n}', kind='interface'), language='typescript'),
                 unit(1, 'read.py', 'def read():\n    return 1')]
        context, debug, _ = self.search(units, query='Find the interface describing the response',
                                       scores=lambda q, d: .99 if 'types.ts' in d else .5)
        self.assertEqual(debug['selected'][0]['id'], 0)
        self.assertIn('interface Response', context)

    def test_malformed_embedding_fails_before_selection(self):
        units = [unit(0, 'app.py', 'def save():\n    pass')]
        engine = EvidenceEngine(units, np.ones((1, 4)), 'http://embed', {})
        with patch('evidence.post', return_value={'data': [{'index': 2, 'embedding': [1, 2, 3, 4]}]}):
            with self.assertRaisesRegex(ValueError, 'indices'):
                engine.search({'intent': 'save', 'facets': []})


if __name__ == '__main__':
    unittest.main()

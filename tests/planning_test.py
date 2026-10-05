"""Query decomposition preserves conditions without mistaking them for objectives."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/retrieval'))
from planning import plan_query


class PlanningTest(unittest.TestCase):
    def test_condition_is_context_not_a_standalone_facet(self):
        query = 'When a user opens a record, how is it loaded and how are pending changes merged?'
        plan = plan_query(query)
        self.assertEqual(plan['intent'], query)
        self.assertEqual(len(plan['facets']), 2)
        self.assertFalse(any(f['question'].startswith('When') for f in plan['facets']))

    def test_chinese_condition_stays_in_intent(self):
        query = '用户打开已有记录时，如何读取历史版本，并在继续编辑时保留尚未提交的内容？'
        plan = plan_query(query)
        self.assertEqual(len(plan['facets']), 2)
        self.assertEqual(plan['intent'], query)
        self.assertFalse(any(f['question'].endswith('时') for f in plan['facets']))

    def test_single_question_and_long_enumerations_remain_intact(self):
        for query in ['Find the implementation of storage', 'first behavior; second behavior; third behavior; fourth behavior; fifth behavior; sixth behavior']:
            self.assertEqual(plan_query(query)['facets'][0]['question'], query)

    def test_multiple_behaviors_are_separate_facets(self):
        plan = plan_query('How does the system load older versions and preserve the current selection?')
        self.assertEqual(len(plan['facets']), 2)
        self.assertTrue(plan['facets'][1]['question'].startswith('preserve'))


if __name__ == '__main__':
    unittest.main()

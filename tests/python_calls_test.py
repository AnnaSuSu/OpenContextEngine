"""Static Python relationships must survive source roots without guessing bindings."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/retrieval'))
from languages.python import extract
from languages.schema import SourceFile, validate_units
from languages import adapter_manifest


class PythonCallsTest(unittest.TestCase):
    def calls(self, sources, name):
        units = extract([SourceFile(p, text, '') for p, text in sources.items()])
        validate_units(units, [SourceFile(p, text, '') for p, text in sources.items()])
        return {units[r['target']]['symbol'] for u in units if u['name'] == name
                for r in u['relations'] if r['kind'] == 'calls'}

    def test_local_import_source_root_and_split_function(self):
        sources = {'backend/app/service.py': 'def filter_config():\n    return 1\n',
                   'tests/test_api.py': 'def check():\n    from app.service import filter_config as clean\n    return clean()\n'}
        self.assertEqual(self.calls(sources, 'check'), {'backend.app.service.filter_config'})

    def test_relative_import_module_alias_and_nested_closure(self):
        sources = {'src/pkg/helper.py': 'def save():\n    pass\n',
                   'src/pkg/main.py': 'from . import helper as storage\ndef run():\n    def nested():\n        storage.save()\n    nested()\n'}
        self.assertEqual(self.calls(sources, 'run'), {'src.pkg.helper.save'})

    def test_parameter_local_assignment_and_import_order_shadow_outer(self):
        source = 'from app.helper import save\ndef parameter(save):\n    save()\ndef assigned():\n    save()\n    save = object()\n    save()\ndef before_import():\n    save()\n    from missing import save\ndef rebound():\n    from app.helper import save\n    save = object()\n    save()\n'
        sources = {'src/app/helper.py': 'def save():\n    pass\n', 'use.py': source}
        for name in ['parameter', 'assigned', 'before_import', 'rebound']:
            with self.subTest(name=name):
                self.assertEqual(self.calls(sources, name), set())

    def test_conditional_import_cannot_leak_but_resolves_in_branch(self):
        sources = {'app/helper.py': 'def save():\n    pass\n', 'use.py':
                   'def uncertain(flag):\n    if flag:\n        from app.helper import save\n    save()\ndef inside(flag):\n    if flag:\n        from app.helper import save\n        save()\n'}
        self.assertEqual(self.calls(sources, 'uncertain'), set())
        self.assertEqual(self.calls(sources, 'inside'), {'app.helper.save'})

    def test_ambiguous_suffix_and_dynamic_receiver_are_not_guessed(self):
        sources = {'first/app/helper.py': 'def save():\n    pass\n',
                   'second/app/helper.py': 'def save():\n    pass\n',
                   'use.py': 'from app.helper import save\ndef run(client):\n    save()\n    client.save()\n'}
        self.assertEqual(self.calls(sources, 'run'), set())

    def test_exact_module_wins_over_source_root_suffix(self):
        sources = {'app/helper.py': 'def save():\n    pass\n',
                   'src/app/helper.py': 'def save():\n    pass\n',
                   'use.py': 'import app.helper as helper\ndef run():\n    helper.save()\n'}
        self.assertEqual(self.calls(sources, 'run'), {'app.helper.save'})

    def test_comprehension_and_lambda_bindings_do_not_resolve_outer_import(self):
        sources = {'app/helper.py': 'def save():\n    pass\n', 'use.py':
                   'from app.helper import save\ndef run(items):\n    [save() for save in items]\n    callback = lambda save: save()\n'}
        self.assertEqual(self.calls(sources, 'run'), set())

    def test_class_locals_do_not_shadow_module_bindings_in_methods(self):
        sources = {'app/helper.py': 'def save():\n    pass\n', 'use.py':
                   'from app.helper import save\nclass Service:\n    save = object()\n    def run(self):\n        save()\n'}
        self.assertEqual(self.calls(sources, 'Service.run'), {'app.helper.save'})

    def test_function_attributes_are_references_not_claimed_calls(self):
        sources = {'app/helper.py': 'def run():\n    pass\n', 'test_main.py':
                   'def check():\n    from app.helper import run\n    run.invoke({})\n'}
        self.assertEqual(self.calls(sources, 'check'), set())
        units = extract([SourceFile(p, text, '') for p, text in sources.items()])
        self.assertEqual({units[r['target']]['symbol'] for u in units if u['name'] == 'check'
                          for r in u['relations'] if r['kind'] == 'references_value'}, {'app.helper.run'})

    def test_explicit_function_reference_retains_source_provenance(self):
        sources = {'app.py': 'def clean():\n    return 1\ndef merge():\n    """See :func:`clean` before mutation."""\n    return 2\n'}
        units = extract([SourceFile(p, text, '') for p, text in sources.items()])
        refs = [r for u in units if u['name'] == 'merge' for r in u['relations']]
        self.assertTrue(any(r['kind'] == 'references_value' and r['resolution'] == 'explicit-doc-reference' for r in refs))
        self.assertEqual(self.calls(sources, 'merge'), set())

    def test_index_identity_includes_resolver(self):
        self.assertIn('python_calls.py', adapter_manifest([{'path': 'app.py'}])['sourceSha256'])


if __name__ == '__main__':
    unittest.main()

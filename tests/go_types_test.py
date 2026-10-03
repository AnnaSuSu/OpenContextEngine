"""Compiler binding only links concrete implementations inside the snapshot."""
import unittest
import languages_test
from languages import adapter_manifest


class GoTypesTest(unittest.TestCase):
    def extract(self, sources, max_lines=65, options=None):
        settings = {'go': {'mode': 'types', **(options or {}).get('go', {})}}
        return languages_test.LanguageAdaptersTest.extract(self, sources, max_lines, settings)

    targets = languages_test.LanguageAdaptersTest.targets

    def test_module_alias_cross_file_receiver_and_generic_function_bindings(self):
        units = self.extract({
            'go.mod': 'module example.test/project\n\ngo 1.22\n',
            'store/store.go': 'package store\ntype Store struct {}\n'
                'func (s *Store) Save() int { return 1 }\n'
                'func New() *Store { return &Store{} }\n'
                'func Identity[T any](v T) T { return v }\n',
            'app/main.go': 'package app\nimport storage "example.test/project/store"\n'
                'func Run() int { s := storage.New(); return storage.Identity(s.Save()) }\n',
        })
        calls = self.targets(units, 'Run', 'calls')
        self.assertEqual({symbol.split('::')[1].split('@')[0] for symbol in calls}, {'New', 'Store.Save', 'Identity'})
        self.assertTrue(all(r['resolution'] == 'compiler-symbol' for u in units for r in u['relations'] if r['kind'] == 'calls'))
        self.assertTrue(any(r['kind'] == 'references_type' for u in units for r in u['relations']))

    def test_promoted_concrete_method_binds_but_interface_and_callback_do_not(self):
        units = self.extract({'main.go': 'package p\ntype Store struct {}\n'
            'func (*Store) Save() int { return 1 }\ntype Wrapped struct { Store }\n'
            'type Saver interface { Save() int }\n'
            'func concrete(w *Wrapped) int { return w.Save() }\n'
            'func dynamic(s Saver) int { return s.Save() }\n'
            'func callback(Save func() int) int { return Save() }\n'})
        self.assertTrue(self.targets(units, 'concrete', 'calls'))
        self.assertEqual(self.targets(units, 'dynamic', 'calls'), set())
        self.assertEqual(self.targets(units, 'callback', 'calls'), set())

    def test_build_target_selects_binding_without_removing_other_source(self):
        sources = {'main.go': 'package p\nfunc run() { save() }\n',
            'impl_linux.go': 'package p\nfunc save() {}\n',
            'impl_windows.go': 'package p\nfunc save() {}\n',
            'extra.go': '//go:build custom\n\npackage p\nfunc save() {}\n'}
        for target in ['linux', 'windows']:
            units = self.extract(sources, options={'go': {'goos': target}})
            self.assertEqual(self.targets(units, 'run', 'calls'), {f'impl_{target}.go::save@2'})
            self.assertEqual({u['path'] for u in units}, set(sources))
            self.assertFalse(next(u['goAnalysis']['selectedForTypes'] for u in units if u['path'] == 'extra.go'))

    def test_missing_dependencies_preserve_local_bindings_and_report_diagnostics(self):
        units = self.extract({'main.go': 'package p\nimport "outside.invalid/dependency"\n'
            'func local() {}\nfunc run() { local(); dependency.Save() }\n'})
        self.assertEqual(self.targets(units, 'run', 'calls'), {'main.go::local@3'})
        diagnostics = [message for u in units for message in u.get('goAnalysis', {}).get('diagnostics', [])]
        self.assertTrue(any('outside source snapshot' in message for message in diagnostics))

    def test_duplicate_declarations_do_not_create_arbitrary_binding(self):
        units = self.extract({'a.go': 'package p\nfunc save() {}\n',
            'b.go': 'package p\nfunc save() {}\nfunc run() { save() }\n'})
        self.assertEqual(self.targets(units, 'run', 'calls'), set())

    def test_parser_modes_and_target_are_explicit_and_fingerprinted(self):
        files = [{'path': 'main.go'}]
        syntax = adapter_manifest(files, {'go': {'mode': 'syntax'}})
        typed = adapter_manifest(files, {'go': {'mode': 'types'}})
        self.assertNotEqual(syntax, typed)
        self.assertIn('go_types.go', typed['sourceSha256'])
        for settings in [{'goos': 'unknown'}, {'modulePath': '../escape'}, {'plugins': ['run']}, {'mode': 'unknown'}]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.extract({'main.go': 'package p\n'}, options={'go': settings})

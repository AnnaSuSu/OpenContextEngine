"""Structural language fixtures, source coverage, binding and isolation."""
import unittest
import languages_test
from languages import adapter_manifest


class JavaScriptGoTest(unittest.TestCase):
    extract = languages_test.LanguageAdaptersTest.extract
    targets = languages_test.LanguageAdaptersTest.targets

    def test_js_esm_commonjs_and_mixed_typescript(self):
        units = self.extract({
            'store.js': 'export function save(value) { return value; }\n',
            'main.ts': 'import { save } from "./store.js";\nexport function run() { return save(1); }\n',
            'lib.cjs': 'exports.persist = function persist(v) { return v; };\n',
            'consumer.cjs': 'const lib = require("./lib.cjs");\nfunction use() { return lib.persist(1); }\n',
            'panel.jsx': 'export const Panel = () => <div>hello</div>;\n',
            'shim.mjs': 'export { save } from "./store.js";\n',
        })
        self.assertEqual(self.targets(units, 'run', 'calls'), {'store::save'})
        self.assertTrue(self.targets(units, 'use', 'calls'))
        self.assertTrue(any(u['language'] == 'javascript' and u['name'] == 'Panel' for u in units))
        self.assertTrue(any(units[r['target']]['language'] != u['language']
                            for u in units for r in u['relations'] if r['kind'] == 'calls'))

    def test_javascript_shadowed_callbacks_are_not_guessed(self):
        units = self.extract({'main.js': 'function save() {}\n'
            'function run(save) { save(); }\nfunction dynamic(client) { client.save(); }\n'})
        self.assertEqual(self.targets(units, 'run', 'calls'), set())
        self.assertEqual(self.targets(units, 'dynamic', 'calls'), set())

    def test_js_unicode_separators_do_not_move_definitions_or_call_sites(self):
        units = self.extract({'main.js': 'export function f() { return "a\u2028b"; }\r\n'
            'export function g() { return f(); }\r\n'})
        self.assertEqual([(u['name'], u['start'], u['end']) for u in units], [('f', 1, 1), ('g', 2, 2)])
        self.assertEqual(self.targets(units, 'g', 'calls'), {'main::f'})

    def test_go_declarations_same_package_and_shadowing(self):
        units = self.extract({
            'pkg/save.go': 'package pkg\n// Save a value.\nfunc Save() int { return 1 }\n',
            'pkg/main.go': 'package pkg\ntype Store struct {}\nfunc (s *Store) Run() int { return Save() }\n'
                'func shadow(Save func() int) int { return Save() }\n',
            'other/main.go': 'package other\nfunc Save() {}\n',
        })
        calls = self.targets(units, 'Store.Run', 'calls')
        self.assertEqual(len(calls), 1)
        self.assertTrue(next(iter(calls)).startswith('pkg/save.go::Save@'))
        self.assertEqual(self.targets(units, 'shadow', 'calls'), set())
        self.assertTrue(any(u['kind'] == 'type' and u['name'] == 'Store' for u in units))
        self.assertTrue(any(u['text'].startswith('// Save') for u in units))

    def test_go_does_not_guess_dynamic_or_duplicate_package_functions(self):
        units = self.extract({
            'pkg/a_linux.go': 'package p\nfunc Save() {}\n',
            'pkg/a_windows.go': 'package p\nfunc Save() {}\n',
            'pkg/main.go': 'package p\nfunc run(client interface { Save() }) {\n Save()\n client.Save()\n}\n',
        })
        self.assertEqual(self.targets(units, 'run', 'calls'), set())

    def test_go_physical_lines_ignore_line_directives_and_unicode(self):
        units = self.extract({'main.go': 'package p\r\n//line fake.go:1000\r\n'
            'func run() string {\r\n return "a\u2028b"\r\n}\r\n'}, max_lines=2)
        self.assertTrue(all(u['end'] <= 5 for u in units))
        self.assertTrue(any('\u2028' in u['text'] for u in units))

    def test_go_long_callable_has_lossless_chunks_and_real_same_symbol_edges(self):
        units = self.extract({'main.go': 'package p\nfunc run() {\n'+
            ''.join(f' value{i} := {i}\n' for i in range(50))+'}\n'}, max_lines=8)
        body = [u for u in units if u['name'] == 'run']
        self.assertGreater(len(body), 1)
        self.assertTrue(all(any(r['kind'] == 'same_symbol' for r in u['relations']) for u in body))
        self.assertTrue(all(u['end']-u['start'] < 8 for u in units))

    def test_javascript_and_go_syntax_errors_do_not_silently_fallback(self):
        for name, text in [('bad.js', 'export function {'), ('bad.go', 'package p\nfunc {')]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'adapter failed'):
                self.extract({name: text})

    def test_go_and_js_fingerprints_include_parser_sources(self):
        manifest = adapter_manifest([{'path': 'a.go'}, {'path': 'b.js'}])
        self.assertIn('go_ast.go', manifest['sourceSha256'])
        self.assertIn('typescript.mjs', manifest['sourceSha256'])
        self.assertIn('go version', manifest['parsers']['go'])

"""Source adapter contract tests; no model or network calls."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'retrieval'))
from languages import source_units, adapter_manifest
from languages.schema import validate_units, SourceFile


class LanguageAdaptersTest(unittest.TestCase):
    def extract(self, sources, max_lines=65, options=None):
        with tempfile.TemporaryDirectory() as directory:
            files = []
            for name, text in sources.items():
                path = Path(directory)/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode())
                files.append({'path': name, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
            units = source_units(directory, files, max_lines, options)
        validate_units(units, [SourceFile(name, text.lstrip('\ufeff'), '') for name, text in sources.items()])
        return units

    def targets(self, units, name, kind):
        return {units[r['target']]['symbol'] for unit in units if unit['name'] == name
                for r in unit['relations'] if r['kind'] == kind}

    def test_typescript_imports_reexports_aliases_inheritance_and_this(self):
        sources = {
            'src/base.ts': 'export interface Shape { id: string; }\n'
                'export class Base {\n  format(v: string) { return v; }\n}\n'
                'export function save(v: string) { return v; }\n'
                'export default function store(v: string) { return save(v); }\n',
            'src/barrel.ts': 'export { save as persist, default } from "./base.js";\n',
            'src/main.ts': 'import store, { persist } from "./barrel.js";\n'
                'import { Base, type Shape } from "@lib/base";\n'
                'import * as storage from "./base.js";\n'
                'export class Service extends Base implements Shape {\n'
                '  id = "service";\n'
                '  run(value: string) {\n'
                '    store(value);\n    storage.save(value);\n    super.format(value);\n'
                '    return this.finish(value);\n  }\n'
                '  finish(value: string) { return persist(value); }\n}\n',
        }
        units = self.extract(sources, max_lines=5, options={'typescript': {'baseUrl': '.', 'paths': {'@lib/*': ['src/*']}}})
        self.assertEqual(self.targets(units, 'Service.run', 'calls'),
                         {'src/base::store', 'src/base::save', 'src/base::Base.format', 'src/main::Service.finish'})
        self.assertEqual(self.targets(units, 'Service.finish', 'calls'), {'src/base::save'})
        self.assertEqual(self.targets(units, 'Service', 'inherits'), {'src/base::Base'})
        self.assertEqual(self.targets(units, 'Service', 'implements'), {'src/base::Shape'})
        self.assertEqual(self.targets(units, 'Service.run', 'member_of'), {'src/main::Service'})
        self.assertTrue(any(r['kind'] == 'imports' for u in units for r in u['relations']))
        self.assertTrue(all(u['end'] - u['start'] < 5 for u in units))

    def test_dynamic_receivers_callbacks_shadowing_and_external_calls_are_not_guessed(self):
        units = self.extract({'mod.ts': 'export function save(v: string) { return v; }\n'
            'export function dynamic(client: any) { client.save("x"); }\n'
            'export function shadow(save: (v: string) => void) { save("x"); }\n'
            'import { external } from "not-in-the-snapshot";\n'
            'export const run = () => external();\n'})
        for name in ['dynamic', 'shadow', 'run']:
            self.assertEqual(self.targets(units, name, 'calls'), set())
            self.assertTrue(any(u['unresolved'] for u in units if u['name'] == name))

    def test_tsx_mts_cts_long_functions_and_same_line_members_preserve_source(self):
        units = self.extract({
            'panel.tsx': '\ufeffinterface Props { title: string; }\r\n'
                'export const Panel = (p: Props) => <div>{p.title}</div>;\r\n',
            'long.mts': 'export function long() {\n' + ''.join(f'  const n{i} = {i};\n' for i in range(25)) + '}\n',
            'same.cts': 'export class Pair { left() { return this.right(); } right() { return 1; } }\n',
        }, max_lines=5)
        self.assertTrue(any(u['name'] == 'Panel' and u['kind'] == 'function' for u in units))
        self.assertEqual(self.targets(units, 'Panel', 'references_type'), {'panel::Props'})
        long = [u for u in units if u['name'] == 'long']
        self.assertGreater(len(long), 1)
        self.assertTrue(all(any(r['kind'] == 'same_symbol' for r in u['relations']) for u in long))
        self.assertTrue(all(u['language'] == 'typescript' for u in units))

    def test_mixed_snapshot_keeps_file_order_and_language_local_relations(self):
        units = self.extract({'a.ts': 'import { run } from "./b.js";\nexport const start = () => run();\n',
                              'p.py': 'def py():\n    return 1\n',
                              'b.ts': 'export function run() { return 1; }\n'})
        paths = list(dict.fromkeys(u['path'] for u in units))
        self.assertEqual(paths, ['a.ts', 'p.py', 'b.ts'])
        self.assertEqual(self.targets(units, 'start', 'calls'), {'b::run'})
        self.assertTrue(all(units[r['target']]['language'] == u['language'] for u in units for r in u['relations']))

    def test_hash_paths_and_invalid_options_fail_but_syntax_degrades(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'a.py'; p.write_text('def f(): pass\n')
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                source_units(directory, [{'path': 'a.py', 'sha256': 'bad'}])
            with self.assertRaisesRegex(ValueError, 'snapshot path'):
                source_units(directory, [{'path': '../a.py', 'sha256': 'bad'}])
            (Path(directory)/'a.go').write_text('package main\n')
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                source_units(directory, [{'path': 'a.go', 'sha256': 'bad'}])
        broken = self.extract({'broken.ts': 'export function broken( {\n'})
        self.assertEqual(broken[0]['language'], 'text')
        self.assertEqual(broken[0]['parseDiagnostic']['language'], 'typescript')
        with self.assertRaisesRegex(ValueError, 'options'):
            self.extract({'a.ts': 'const a = 1;\n'}, options={'typescript': {'plugins': []}})

    def test_adapter_identity_captures_languages_source_and_resolution_options(self):
        files = [{'path': 'a.ts', 'sha256': 'example'}]
        before = adapter_manifest(files)
        after = adapter_manifest(files, {'typescript': {'paths': {'@/*': ['src/*']}}})
        self.assertNotEqual(before, after)
        self.assertIn('typescript.mjs', before['sourceSha256'])
        self.assertEqual(before['parsers']['typescript'], 'typescript-5.9.3')


if __name__ == '__main__':
    unittest.main()

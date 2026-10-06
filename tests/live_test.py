from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from live import LiveIndex, IndexUnavailable, SourceChanged
from languages import source_units


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base/'repo'
        self.root.mkdir()
        self.calls = []
        self.managers = []
        self.config = {'root':str(self.root),'state':str(self.base/'state'),
                       'embeddingIdentity':'https://model.example/v1', 'embeddingUrl':'http://test/v1',
                       'embeddingKey':'test-key', 'reranker':{}, 'pollSeconds':.05,'debounceSeconds':0}

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.temp.cleanup()

    def embed(self, url, body, key, timeout):
        self.calls.extend(body['input'])
        return {'data':[{'index':i, 'embedding':[1.] + [0.]*1023} for i in range(len(body['input']))]}

    def manager(self, **changes):
        manager = LiveIndex({**self.config, **changes}, embed=self.embed,
                            engine_factory=lambda units, *args, **kwargs: units)
        self.managers.append(manager)
        return manager

    def write(self, path, text):
        (self.root/path).write_text(text)

    def build(self, manager):
        snapshot = manager.scan()
        generation = manager._build(snapshot, manager.identity(snapshot))
        manager.generation = generation
        return generation

    def test_edit_delete_rename_and_line_shift_reuse(self):
        self.write('a.py','def one():\n    return 1\n\ndef two():\n    return 2\n')
        self.write('b.txt','stable text\n')
        manager = self.manager()
        first = self.build(manager)
        self.assertEqual(first.info['embeddedDocuments'], 3)
        self.write('a.py','\n\ndef one():\n    return 1\n\ndef two():\n    return 3\n')
        second = self.build(manager)
        self.assertEqual(second.info['embeddedDocuments'], 1)
        self.assertEqual(second.engine[0]['start'], 3)
        self.assertEqual(second.info['reusedUnits'], 2)
        (self.root/'b.txt').rename(self.root/'c.txt')
        third = self.build(manager)
        self.assertEqual(third.info['deletedFiles'], 1)
        self.assertEqual(third.info['embeddedDocuments'], 1)
        (self.root/'a.py').unlink()
        fourth = self.build(manager)
        self.assertEqual(fourth.info['embeddedDocuments'], 0)
        self.assertEqual({unit['path'] for unit in fourth.engine}, {'c.txt'})

    def test_provider_batch_limit_and_cache_reuse(self):
        for i in range(43):
            self.write(f'{i}.txt', f'unique document {i}\n')
        manager = self.manager(embeddingBatchSize=20)
        sizes = []
        def embed(url, body, key, timeout):
            sizes.append(len(body['input']))
            return self.embed(url, body, key, timeout)
        manager.embed = embed
        built = self.build(manager)
        self.assertEqual(sizes, [20, 20, 3])
        manager.close()
        restored = self.manager(embeddingBatchSize=10)
        self.assertEqual(restored.identity(restored.scan()), built.identity)
        self.assertEqual(self.build(restored).info['embeddedDocuments'], 0)

    def test_invalid_embedding_batch_size(self):
        for value in [0, 65, True, 1.5, '20', None]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'batch size'):
                self.manager(embeddingBatchSize=value)

    def test_cross_file_relations_refresh_and_units_equal_full_build(self):
        self.write('lib.py','def save():\n    pass\n')
        self.write('main.py','from lib import save\ndef run():\n    save()\n')
        manager = self.manager()
        first = self.build(manager)
        self.assertTrue(any(r['kind']=='calls' for u in first.engine for r in u['relations']))
        self.write('lib.py','def renamed():\n    pass\n')
        second = self.build(manager)
        self.assertFalse(any(r['kind']=='calls' for u in second.engine for r in u['relations']))
        self.assertEqual(second.engine, source_units(self.root, manager.scan()['files']))
        self.assertEqual(second.info['embeddedDocuments'], 1)

    def test_branch_switch_reuses_saved_vectors(self):
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        self.write('a.txt','original\n')
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid',
                        'commit','-qm','original'],check=True)
        original = subprocess.check_output(['git','-C',str(self.root),'rev-parse','HEAD'],text=True).strip()
        manager = self.manager()
        self.build(manager)
        subprocess.run(['git','-C',str(self.root),'switch','-qc','feature'],check=True)
        self.write('a.txt','feature\n')
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid',
                        'commit','-qm','feature'],check=True)
        self.build(manager)
        subprocess.run(['git','-C',str(self.root),'switch','-q','--detach',original],check=True)
        reverted = self.build(manager)
        self.assertEqual(reverted.info['embeddedDocuments'],0)
        self.assertEqual(reverted.engine[0]['text'],'original')

    def test_restart_restores_and_provider_revision_invalidates(self):
        self.write('a.txt','stable\n')
        first = self.manager()
        built = self.build(first)
        first.close()
        second = self.manager()
        snapshot = second.scan()
        restored = second._restore(snapshot,second.identity(snapshot))
        self.assertEqual(restored.identity,built.identity)
        second.close()
        third = self.manager(embeddingRevision='2')
        self.assertIsNone(third._restore(third.scan(),third.identity(third.scan())))
        self.assertEqual(self.build(third).info['embeddedDocuments'],1)

    def test_syntax_fallback_replaces_stale_code_and_recovers(self):
        self.write('a.py','def f():\n    return 1\n')
        manager = self.manager().start()
        first = manager.current(5)
        self.write('a.py','def broken(\n')
        degraded = manager.current(5)
        self.assertNotEqual(degraded.identity, first.identity)
        self.assertEqual(degraded.info['degradedFiles'], 1)
        self.assertEqual(degraded.engine[0]['text'], 'def broken(')
        self.assertEqual(degraded.engine[0]['language'], 'text')
        with self.assertRaises(IndexUnavailable):
            manager.verify(first)
        self.write('a.py','def f():\n    return 2\n')
        fixed = manager.current(5)
        self.assertNotEqual(fixed.identity,first.identity)
        self.assertEqual(fixed.info['degradedFiles'], 0)
        self.assertEqual(fixed.info['parseDiagnostics'], [])
        self.assertEqual(fixed.engine[0]['language'], 'python')
        with self.assertRaises(IndexUnavailable):
            manager.verify(first)

    def test_syntax_diagnostics_survive_parse_cache_and_restart(self):
        self.write('template.py', 'def <entry_point>():\n    pass\n')
        manager = self.manager()
        first = self.build(manager)
        self.write('settings.txt', 'new file\n')
        cached = self.build(manager)
        self.assertEqual(cached.info['parseDiagnostics'], first.info['parseDiagnostics'])
        manager.close()
        reopened = self.manager()
        snapshot = reopened.scan()
        restored = reopened._restore(snapshot, reopened.identity(snapshot))
        self.assertEqual(restored.info['parseDiagnostics'], first.info['parseDiagnostics'])
        (self.root/'template.py').unlink()
        self.assertEqual(self.build(reopened).info['degradedFiles'], 0)

    def test_embedding_failure_still_blocks_stale_queries(self):
        self.write('a.py', 'def f():\n    return 1\n')
        manager = self.manager()
        first = self.build(manager)
        manager.embed = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('model unavailable'))
        self.write('a.py', 'def f():\n    return 2\n')
        manager.start()
        with self.assertRaisesRegex(IndexUnavailable, 'RuntimeError'):
            manager.current(5)
        self.assertEqual(manager.generation.identity, first.identity)

    def test_background_updates_without_query_and_empty_repository(self):
        manager = self.manager().start()
        empty = manager.current(5)
        self.assertIsNone(empty.engine)
        self.write('new.txt','saved without a commit\n')
        deadline = time.monotonic()+5
        while manager.generation.identity == empty.identity and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertNotEqual(manager.generation.identity,empty.identity)
        (self.root/'new.txt').unlink()
        self.assertIsNone(manager.current(5).engine)

    def test_edit_during_embedding_never_publishes_mixed_generation(self):
        self.write('a.txt','before\n')
        manager = self.manager()
        original = manager.embed
        def edit(*args, **kwargs):
            self.write('a.txt','after\n')
            return original(*args, **kwargs)
        manager.embed = edit
        with self.assertRaises(SourceChanged):
            self.build(manager)
        self.assertFalse((manager.state/'current.json').exists())
        manager.embed = original
        self.assertEqual(self.build(manager).engine[0]['text'],'after')

    def test_pending_wait_and_failed_embedding_are_explicit(self):
        self.write('a.txt','one\n')
        manager = self.manager()
        with self.assertRaises(IndexUnavailable) as pending:
            manager.current(.05)
        self.assertEqual(pending.exception.code, 'INDEX_UPDATING')
        manager.embed = lambda *args, **kwargs: {'data':[]}
        with self.assertRaisesRegex(ValueError, 'indices'):
            self.build(manager)
        self.assertFalse((manager.state/'current.json').exists())

    def test_embedding_progress_counts_completed_batches_and_excludes_cached_documents(self):
        for i in range(5):
            self.write(f'{i}.txt', f'document {i}\n')
        manager = self.manager(embeddingBatchSize=2)
        observations = []
        def embed(*args, **kwargs):
            observations.append(manager.status()['progress'])
            return self.embed(*args, **kwargs)
        manager.embed = embed
        self.build(manager)
        self.assertEqual(observations, [
            {'stage': 'embedding', 'completedDocuments': n, 'totalDocuments': 5}
            for n in [0, 2, 4]])
        self.assertEqual(manager.status()['progress']['stage'], 'finalizing')
        observations.clear()
        self.write('0.txt', 'changed document\n')
        self.build(manager)
        self.assertEqual(observations, [
            {'stage': 'embedding', 'completedDocuments': 0, 'totalDocuments': 1}])

    def test_atomic_publish_failure_keeps_previous_disk_and_memory_version(self):
        self.write('a.txt','before\n')
        manager = self.manager()
        first = self.build(manager)
        pointer = (manager.state/'current.json').read_text()
        self.write('a.txt','after\n')
        with patch('live.os.replace',side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.build(manager)
        self.assertEqual(manager.generation.identity,first.identity)
        self.assertEqual((manager.state/'current.json').read_text(),pointer)
        self.assertEqual(self.build(manager).engine[0]['text'],'after')

    def test_model_change_reembeds_with_new_dimensions_and_name(self):
        self.write('a.txt','content\n')
        first = self.manager()
        self.build(first)
        first.close()
        next_model = self.manager(embeddingModel='test-model-v2',embeddingDimensions=3)
        def embed(url, body, key, timeout):
            self.assertEqual(body['model'],'test-model-v2')
            return {'data':[{'index':i,'embedding':[1,0,0]} for i in range(len(body['input']))]}
        next_model.embed = embed
        self.assertEqual(self.build(next_model).info['embeddedDocuments'],1)

    def test_exclusions_and_single_writer(self):
        self.write('.env','SECRET=do-not-index\n')
        self.write('ok.txt','safe\n')
        (self.root/'link.txt').symlink_to(self.root/'ok.txt')
        manager = self.manager()
        self.assertEqual([f['path'] for f in manager.scan()['files']],['ok.txt'])
        with self.assertRaisesRegex(ValueError,'running writer'):
            self.manager()
        with self.assertRaisesRegex(ValueError,'outside'):
            self.manager(state=str(self.root/'index'))

    def test_cached_mixed_language_units_match_uncached_and_refresh_imports(self):
        self.write('a.js','export function save() { return 1; }\n')
        self.write('b.ts','import { save } from "./a.js";\nexport function run() { return save(); }\n')
        self.write('readme.txt','docs\n')
        manager = self.manager()
        for text in ['export function save() { return 1; }\n','export function renamed() { return 2; }\n']:
            self.write('a.js',text)
            generation = self.build(manager)
            self.assertEqual(generation.engine,source_units(self.root,manager.scan()['files']))
        self.assertFalse(any(r['kind']=='calls' for u in generation.engine for r in u['relations']))

    def test_go_cache_refreshes_unchanged_callers_and_module_configuration(self):
        self.write('go.mod','module example.test/first\n')
        self.write('lib.go','package example\nfunc Save() {}\n')
        self.write('main.go','package example\nfunc Run() { Save() }\n')
        manager = self.manager()
        first = self.build(manager)
        self.assertTrue(any(r['kind']=='calls' for u in first.engine for r in u['relations']))
        self.write('lib.go','package example\nfunc Renamed() {}\n')
        self.write('go.mod','module example.test/second\n')
        second = self.build(manager)
        self.assertFalse(any(r['kind']=='calls' for u in second.engine for r in u['relations']))
        self.assertEqual(second.engine,source_units(self.root,manager.scan()['files']))


if __name__ == '__main__':
    unittest.main()

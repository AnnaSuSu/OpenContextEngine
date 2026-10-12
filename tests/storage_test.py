from contextlib import closing
from pathlib import Path
import gc
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from storage import VectorStore, UnitStore
from shared_index import SharedVectorStore
from languages import source_units
from languages.files import discover_snapshot


class StorageTests(unittest.TestCase):
    def test_shared_collection_keeps_other_workspace_data_and_reclaims_removed_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            states = [base/'one', base/'two']
            for state in states:
                state.mkdir()
                (state/'current.json').write_text('{}')
            stores = [SharedVectorStore(base/'shared', 2, 1, state, threading.Event()) for state in states]
            refs = []
            for i, store in enumerate(stores):
                with store.build_guard(), closing(store.open()) as db:
                    ref = store.put(db, [str(i)], np.array([[i, i+1]], dtype=np.float32))[str(i)]
                    store.save_texts([f'source {i}'])
                    store.retain([ref], prepare=True)
                    store.collect([ref])
                    refs.append(ref)
            # No in-process matrix pins protect the first workspace.
            stores[0].matrix([refs[0]]).validate()
            self.assertEqual(stores[0].load_texts([stores[0].text_key('source 0')]),
                             {stores[0].text_key('source 0'): 'source 0'})
            (states[0]/'current.json').unlink()
            with stores[1].build_guard():
                stores[1].collect([refs[1]])
            self.assertFalse((stores[0].directory/refs[0][0]).exists())
            self.assertTrue((stores[1].directory/refs[1][0]).exists())
            with closing(stores[1].open()) as db:
                self.assertEqual(db.execute('SELECT text FROM source_texts').fetchall(), [('source 1',)])

    def test_shared_collection_rejects_unreadable_manifests_before_deleting_vectors(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base/'workspace'
            workspace.mkdir()
            (workspace/'current.json').write_text('{}')
            store = SharedVectorStore(base/'shared', 2, 1, workspace, threading.Event())
            with store.build_guard(), closing(store.open()) as db:
                ref = store.put(db, ['a'], np.array([[1, 2]], dtype=np.float32))['a']
                (store.manifests/'broken.json').write_text('{broken')
                with self.assertRaises(OSError):
                    store.collect([])
                self.assertTrue((store.directory/ref[0]).exists())
    def test_vector_shards_reuse_rows_pin_old_queries_and_collect_only_unreferenced_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store=VectorStore(Path(directory),2,160)
            with closing(store.open()) as db:
                first=store.put(db,['a','b'],np.array([[1,2],[3,4]],dtype=np.float32))
                old=store.matrix([first['b'],first['a']])
                old.validate()
                second=store.put(db,['c'],np.array([[5,6]],dtype=np.float32))
                current=store.matrix([second['c']])
                current.validate()
                self.assertEqual(store.lookup(db,['a','b']) ,first)
            store.collect([second['c']])
            np.testing.assert_array_equal(old@np.eye(2,dtype=np.float32),[[3,4],[1,2]])
            self.assertEqual(len(list(store.directory.glob('*.npy'))),2)
            del old
            gc.collect()
            store.collect([second['c']])
            self.assertEqual(len(list(store.directory.glob('*.npy'))),1)
            np.testing.assert_array_equal(current@np.ones((2,1),dtype=np.float32),[[11]])

    def test_legacy_blob_cache_migrates_without_embedding_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            with closing(sqlite3.connect(state/'embeddings.sqlite')) as db:
                db.execute('CREATE TABLE vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL)')
                db.execute('INSERT INTO vectors VALUES (?, ?)',('key',np.array([1,2],dtype=np.float32).tobytes()))
                db.commit()
            store=VectorStore(state,2,10000)
            with closing(store.open()) as db:
                refs=store.lookup(db,['key'])
                self.assertEqual(db.execute('SELECT length(value) FROM vectors').fetchone()[0],0)
            restored=store.matrix(json.loads(json.dumps([refs['key']])))
            restored.validate()
            np.testing.assert_array_equal(restored@np.ones((2,1),dtype=np.float32),[[3]])

    def test_corrupt_cached_shard_is_rejected_and_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            store=VectorStore(Path(directory),2,10000)
            value=np.array([[1,2]],dtype=np.float32)
            with closing(store.open()) as db:
                refs=store.put(db,['a'],value)
                (store.directory/refs['a'][0]).write_bytes(b'corrupt')
                self.assertEqual(store.lookup(db,['a']),{})
                restored=store.put(db,['a'],value)
                self.assertEqual(store.lookup(db,['a']),restored)
                store.matrix([restored['a']]).validate()

    def test_source_shards_preserve_graph_ids_and_only_replace_affected_buckets(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);root=state/'repo';root.mkdir()
            (root/'lib.py').write_text('def save():\n    return 1\n')
            (root/'main.py').write_text('from lib import save\ndef run():\n    return save()\n')
            for i in range(500): (root/f'{i}.txt').write_text(f'document {i}\n')
            def extract():return source_units(root,discover_snapshot(root)['files'])
            store=UnitStore(state)
            first=extract();before=store.save(first)
            self.assertEqual(store.load(before),first)
            (root/'0.txt').write_text('edited\n')
            second=extract();after=store.save(second)
            self.assertEqual(store.load(after),second)
            self.assertEqual(len(set(after)-set(before)),1)
            store.collect(after)
            self.assertEqual({p.name for p in store.directory.glob('*.json')},set(after))


if __name__=='__main__':unittest.main()

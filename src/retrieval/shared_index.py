"""Shared immutable data with independent workspace manifests and search graphs."""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import time
import uuid

from cancellation import check
from resources import BuildSlot
from storage import VectorStore, fingerprint
from writer_lock import acquire_writer_lock, WriterBusy


class SharedVectorStore(VectorStore):
    def __init__(self, directory, dimensions, budget, workspace, stop):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Another process may be writing a temporary shard. Cleanup needs the lock.
        super().__init__(directory, dimensions, budget, cleanup=False)
        self.workspace, self.stop = workspace, stop
        self.manifests = directory/'workspaces'
        self.manifests.mkdir(exist_ok=True, mode=0o700)
        self.manifest = self.manifests/(fingerprint(str(workspace))+'.json')
        self.text_keys = []

    @contextmanager
    def build_guard(self, *, update=False):
        # Lookup, embedding, registration and reclamation form one operation.
        # Concurrent workspaces cannot both embed the same missing document.
        with BuildSlot(self.state, 1, self.stop, update=update, name='writer') as slot:
            for temporary in self.directory.glob('*.tmp'):
                temporary.unlink(missing_ok=True)
            yield slot

    @contextmanager
    def build_pin(self):
        """Protect unfinished vectors while their build yields to another worker."""
        directory = self.state/'build-pins'
        directory.mkdir(exist_ok=True, mode=0o700)
        path = directory/(uuid.uuid4().hex+'.json')
        handle = acquire_writer_lock(path.with_suffix('.lock'))
        def protect(references):
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(sorted({name for name, row in references})))
            temporary.replace(path)
        try:
            yield protect
        finally:
            path.unlink(missing_ok=True)
            handle.close()
            path.with_suffix('.lock').unlink(missing_ok=True)

    def open(self):
        db = super().open()
        db.execute('CREATE TABLE IF NOT EXISTS source_texts (key TEXT PRIMARY KEY, text TEXT NOT NULL, used REAL NOT NULL)')
        return db

    @staticmethod
    def text_key(text):
        return hashlib.sha256(text.encode()).hexdigest()

    def save_texts(self, texts):
        keys = [self.text_key(text) for text in texts]
        with closing(self.open()) as db:
            db.executemany('INSERT INTO source_texts VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET text=excluded.text, used=excluded.used WHERE source_texts.text<>excluded.text',
                           [(key, text, time.time()) for key, text in zip(keys, texts)])
            db.commit()
        self.text_keys = keys
        return keys

    def load_texts(self, keys):
        result, wanted = {}, sorted(set(keys))
        with closing(self.open()) as db:
            for offset in range(0, len(wanted), 500):
                check()
                batch = wanted[offset:offset+500]
                placeholders = ','.join('?' for _ in batch)
                result.update(db.execute(f'SELECT key, text FROM source_texts WHERE key IN ({placeholders})', batch))
        if len(result) != len(wanted) or any(self.text_key(text) != key for key, text in result.items()):
            raise ValueError('Missing or corrupt shared source text')
        return result

    def retain(self, references, *, prepare=False):
        vectors = {name for name, row in references}
        for matrix in list(self.pins):
            vectors.update(matrix.groups)
        texts = set(self.text_keys)
        if prepare and self.manifest.exists():
            previous = json.loads(self.manifest.read_text())
            vectors.update(previous['vectorShards'])
            texts.update(previous['textKeys'])
        data = {'workspaceState': str(self.workspace),
                'vectorShards': sorted(vectors), 'textKeys': sorted(texts)}
        temporary = self.manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps(data))
        temporary.replace(self.manifest)

    def collect(self, references):
        # The caller holds build_guard. Each manifest protects disk restoration;
        # local matrix pins also protect searches on previous generations.
        self.retain(references)
        vectors, texts = set(), set()
        for path in (self.state/'build-pins').glob('*.json'):
            try:
                probe = acquire_writer_lock(path.with_suffix('.lock'))
            except WriterBusy:
                try:
                    pins = json.loads(path.read_text())
                except ValueError:
                    raise OSError('Cannot verify unfinished build references') from None
                if not isinstance(pins, list) or any(not isinstance(name, str) for name in pins):
                    raise OSError('Cannot verify unfinished build references')
                vectors.update(pins)
            else:
                path.unlink(missing_ok=True)
                probe.close()
                path.with_suffix('.lock').unlink(missing_ok=True)
        for path in self.manifests.glob('*.json'):
            check()
            try:
                data = json.loads(path.read_text())
                if (not isinstance(data, dict) or not Path(data['workspaceState']).is_absolute()
                        or path.name != fingerprint(data['workspaceState'])+'.json'
                        or not isinstance(data['vectorShards'], list) or not isinstance(data['textKeys'], list)):
                    raise ValueError('Invalid shared workspace manifest')
            except (ValueError, KeyError, TypeError):
                raise OSError('Cannot verify shared workspace references') from None
            if not (Path(data['workspaceState'])/'current.json').is_file():
                path.unlink()
                continue
            vectors.update(data['vectorShards'])
            texts.update(data['textKeys'])
        # Do not reclaim data if a manifest is unreadable: fail closed instead.
        with closing(self.open()) as db:
            source_bytes = db.execute('SELECT coalesce(sum(length(cast(text AS BLOB))),0) FROM source_texts').fetchone()[0]
        budget = self.budget
        try:
            self.budget = max(1, budget-source_bytes)
            super().collect([[name, 0] for name in vectors])
        finally:
            self.budget = budget
        total = source_bytes + sum(path.stat().st_size for path in self.directory.glob('*.npy'))
        with closing(self.open()) as db:
            rows = db.execute('SELECT key, length(cast(text AS BLOB)) FROM source_texts ORDER BY used')
            while total > budget:
                batch = rows.fetchmany(256)
                if not batch:
                    break
                for key, size in batch:
                    if key not in texts and total > budget:
                        db.execute('DELETE FROM source_texts WHERE key=?', (key,))
                        total -= size
            db.commit()

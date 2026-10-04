"""Single-workspace index: durable vector reuse and atomic searchable generations."""
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid

import numpy as np

from engine import document, post
from languages import adapter_manifest, source_units
from languages.files import discover_snapshot
from routed import RoutedEngine
from writer_lock import acquire_writer_lock


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class IndexUnavailable(Exception):
    """The requested working tree has no complete, current searchable generation."""


class SourceChanged(Exception):
    pass


@dataclass(frozen=True)
class Generation:
    identity: str
    snapshot: dict
    info: dict
    engine: object


class LiveIndex:
    def __init__(self, config, *, embed=post, engine_factory=RoutedEngine):
        self.config = config
        self.root = Path(config['root']).resolve()
        self.state = Path(config['state']).resolve()
        if not self.root.is_dir():
            raise ValueError('Repository root must be a directory')
        if self.state.is_relative_to(self.root):
            raise ValueError('Live index state must be outside the repository root')
        self.options = config.get('languageOptions', {})
        self.poll = float(config.get('pollSeconds', 1))
        self.debounce = float(config.get('debounceSeconds', .3))
        if not .05 <= self.poll <= 60 or not 0 <= self.debounce <= 10:
            raise ValueError('Invalid live index polling or debounce interval')
        self.embedding = {'provider': config['embeddingIdentity'],
                          'model': config.get('embeddingModel', 'Qwen3-Embedding-4B'),
                          'dimensions': config.get('embeddingDimensions', 1024),
                          'revision': config.get('embeddingRevision', '1')}
        if not isinstance(self.embedding['model'], str) or not self.embedding['model']:
            raise ValueError('Invalid embedding model')
        self.dimensions = self.embedding['dimensions']
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= 65536:
            raise ValueError('Invalid embedding dimensions')
        self.embed, self.engine_factory = embed, engine_factory
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.generation = None
        self.error = None
        self.phase = 'starting'
        self.parse_cache = {}
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_file = acquire_writer_lock(self.state/'writer.lock')
        self.thread = threading.Thread(target=self._run, name='repository-index', daemon=True)

    def scan(self):
        snapshot = discover_snapshot(self.root)
        # Ignore diagnostic exclusions and mtime: identities bind actual inputs.
        snapshot = {'files': [{'path': f['path'], 'sha256': f['sha256']} for f in snapshot['files']],
                    'languageOptions': self.options}
        return snapshot

    def identity(self, snapshot):
        return digest({'schema': 'live-index-v1', 'root': str(self.root), 'snapshot': snapshot,
                       'adapters': adapter_manifest(snapshot['files'], self.options),
                       'embedding': self.embedding})

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
        # An in-flight model call may finish later. Keep its writer lock until
        # the worker exits, rather than allowing another process to overlap it.
        if not self.thread.is_alive() and not self.lock_file.closed:
            self.lock_file.close()

    def status(self):
        with self.condition:
            return {'status': self.phase, 'mode': 'live', 'root': str(self.root),
                    'generation': self.generation.info if self.generation else None,
                    'error': self.error, 'pollSeconds': self.poll}

    def current(self, timeout=30):
        deadline = time.monotonic() + timeout
        while not self.stop_event.is_set():
            try:
                target = self.identity(self.scan())
            except (OSError, ValueError) as error:
                raise IndexUnavailable('Cannot read current source: ' + type(error).__name__) from None
            with self.condition:
                if self.generation and self.generation.identity == target:
                    return self.generation
                if self.error and self.error['identity'] == target:
                    raise IndexUnavailable('Index update failed: ' + self.error['type'])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IndexUnavailable('Index update pending; retry after synchronization')
                self.condition.wait(min(remaining, self.poll))
        raise IndexUnavailable('Index is stopping')

    def verify(self, generation):
        try:
            current = self.identity(self.scan()) == generation.identity
        except (OSError, ValueError):
            current = False
        if not current:
            raise IndexUnavailable('Source changed during search; retry for current code')

    def _engine(self, units, vectors):
        if not units:
            return None
        return self.engine_factory(units, vectors, self.config['embeddingUrl'],
                                   self.config['reranker'], self.config.get('embeddingKey', 'local-only'),
                                   embedding_model=self.embedding['model'])

    def _restore(self, snapshot, identity):
        pointer = self.state/'current.json'
        if not pointer.exists():
            return None
        try:
            saved = json.loads(pointer.read_text())
            name = saved['directory']
            if name != Path(name).name or not name.startswith('generation-'):
                return None
            folder = self.state/name
            info = json.loads((folder/'metadata.json').read_text())
            if info['identity'] != identity:
                return None
            units = json.loads((folder/'units.json').read_text())
            vectors = np.load(folder/'vectors.npy', allow_pickle=False)
            if vectors.shape != (len(units), self.dimensions) or not np.isfinite(vectors).all():
                return None
            return Generation(identity, snapshot, info, self._engine(units, vectors))
        except (OSError, ValueError, KeyError):
            return None

    def _build(self, snapshot, identity):
        start = time.monotonic()
        units = source_units(self.root, snapshot['files'], language_options=self.options, cache=self.parse_cache)
        documents = [document(unit) for unit in units]
        keys = [digest([self.embedding, text]) for text in documents]
        vectors, missing = {}, {}
        with closing(sqlite3.connect(self.state/'embeddings.sqlite')) as db:
            db.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL)')
            for key, text in zip(keys, documents):
                row = db.execute('SELECT value FROM vectors WHERE key=?', (key,)).fetchone()
                if row:
                    value = np.frombuffer(row[0], dtype=np.float32)
                    if value.shape == (self.dimensions,) and np.isfinite(value).all():
                        vectors[key] = value
                        continue
                missing[key] = text
            entries = list(missing.items())
            for offset in range(0, len(entries), 64):
                if self.stop_event.is_set():
                    raise SourceChanged()
                batch = entries[offset:offset+64]
                result = self.embed(self.config['embeddingUrl']+'/embeddings',
                    {'model': self.embedding['model'], 'input': [text for _, text in batch]},
                    self.config.get('embeddingKey', 'local-only'), timeout=60)
                rows = sorted(result['data'], key=lambda row: row['index'])
                if [row['index'] for row in rows] != list(range(len(batch))):
                    raise ValueError('Invalid embedding response indices')
                matrix = np.asarray([row['embedding'] for row in rows], dtype=np.float32)
                if matrix.shape != (len(batch), self.dimensions) or not np.isfinite(matrix).all():
                    raise ValueError('Invalid embedding vectors')
                for (key, _), vector in zip(batch, matrix):
                    vectors[key] = vector
                    db.execute('INSERT OR REPLACE INTO vectors VALUES (?, ?)', (key, vector.tobytes()))
                db.commit()  # Reuse successful batches even after a concurrent edit.
        matrix = np.asarray([vectors[key] for key in keys], dtype=np.float32).reshape(len(keys), self.dimensions)
        engine = self._engine(units, matrix)
        if self.stop_event.is_set() or self.scan() != snapshot:
            raise SourceChanged()
        previous = {f['path']: f['sha256'] for f in self.generation.snapshot['files']} if self.generation else {}
        now = {f['path']: f['sha256'] for f in snapshot['files']}
        info = {'identity': identity, 'files': len(now), 'units': len(units),
                'embeddedDocuments': len(missing), 'reusedUnits': sum(key not in missing for key in keys),
                'changedFiles': sum(previous.get(path) != sha for path, sha in now.items()),
                'deletedFiles': len(previous.keys() - now.keys()), 'embedding': self.embedding,
                'languageUnits': dict(Counter(unit['language'] for unit in units)),
                'indexingMs': round((time.monotonic()-start)*1000), 'completedAt': time.time()}
        folder = self.state/('generation-'+uuid.uuid4().hex)
        folder.mkdir(mode=0o700)
        try:
            (folder/'units.json').write_text(json.dumps(units))
            np.save(folder/'vectors.npy', matrix)
            (folder/'metadata.json').write_text(json.dumps(info))
            pointer = self.state/'current.tmp'
            pointer.write_text(json.dumps({'directory': folder.name}))
            os.replace(pointer, self.state/'current.json')
        except BaseException:
            shutil.rmtree(folder)
            raise
        # Search retains its own immutable in-memory generation.
        for old in self.state.glob('generation-*'):
            if old != folder and old.is_dir():
                shutil.rmtree(old)
        return Generation(identity, snapshot, info, engine)

    def _run(self):
        failed_identity, retry_at = None, 0
        try:
            while not self.stop_event.is_set():
                identity = None
                try:
                    snapshot = self.scan()
                    identity = self.identity(snapshot)
                    if self.generation and self.generation.identity == identity:
                        with self.condition:
                            self.phase, self.error = 'ready', None
                        self.stop_event.wait(self.poll)
                        continue
                    if failed_identity == identity and time.monotonic() < retry_at:
                        self.stop_event.wait(self.poll)
                        continue
                    with self.condition:
                        self.phase, self.error = 'updating', None
                    if self.stop_event.wait(self.debounce):
                        break
                    if self.scan() != snapshot:
                        continue
                    generation = self._restore(snapshot, identity) or self._build(snapshot, identity)
                    if self.scan() != snapshot:
                        raise SourceChanged()
                    with self.condition:
                        self.generation, self.phase, self.error = generation, 'ready', None
                        failed_identity = None
                        self.condition.notify_all()
                except SourceChanged:
                    continue
                except Exception as error:
                    failed_identity, retry_at = identity, time.monotonic() + max(2, self.poll)
                    with self.condition:
                        self.phase = 'failed'
                        self.error = {'identity': identity, 'type': type(error).__name__}
                        self.condition.notify_all()
                    self.stop_event.wait(self.poll)
        finally:
            self.lock_file.close()

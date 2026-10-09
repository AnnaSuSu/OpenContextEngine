"""Single-workspace index: durable vector reuse and atomic searchable generations."""
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import sqlite3
import threading
import time
import uuid

import numpy as np

from engine import document, post
from cancellation import check, submit, RequestScope, Cancelled
from resources import acquire_slot, build_slot
from storage import VectorStore, UnitStore
from languages import adapter_manifest, source_units
from languages.files import discover_snapshot
from evidence import EvidenceEngine
from writer_lock import acquire_writer_lock


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class IndexUnavailable(Exception):
    """The requested working tree has no complete, current searchable generation."""

    def __init__(self, message, *, code='INDEX_UNAVAILABLE'):
        super().__init__(message)
        self.code = code


class SourceChanged(Exception):
    pass


@dataclass(frozen=True)
class Generation:
    identity: str
    snapshot: dict
    info: dict
    engine: object


class LiveIndex:
    def __init__(self, config, *, embed=post, engine_factory=EvidenceEngine):
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
        self.idle_seconds = float(config.get('scanIdleSeconds', 60))
        self.unload_seconds = float(config.get('unloadIdleSeconds', 120))
        self.resource_directory = Path(config.get('resourceDirectory', self.state.parent/'.resources'))
        self.resident_slot = None
        self.max_resident = int(config.get('maxResidentWorkers', 3))
        self.max_builds = int(config.get('maxConcurrentBuilds', 1))
        if not 1 <= self.max_resident <= 32 or not 1 <= self.max_builds <= 8 or not .05 <= self.unload_seconds <= 3600:
            raise ValueError('Invalid resource limits')
        if not .05 <= self.poll <= 60 or not 0 <= self.debounce <= 10:
            raise ValueError('Invalid live index polling or debounce interval')
        if not .05 <= self.idle_seconds <= 3600:
            raise ValueError('Invalid live index scan idle interval')
        self.embedding = {'provider': config['embeddingIdentity'],
                          'model': config.get('embeddingModel', 'Qwen3-Embedding-4B'),
                          'dimensions': config.get('embeddingDimensions', 1024),
                          'revision': config.get('embeddingRevision', '1')}
        if not isinstance(self.embedding['model'], str) or not self.embedding['model']:
            raise ValueError('Invalid embedding model')
        self.dimensions = self.embedding['dimensions']
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= 65536:
            raise ValueError('Invalid embedding dimensions')
        self.batch_size = config.get('embeddingBatchSize', 64)
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 64:
            raise ValueError('Embedding batch size must be an integer from 1 to 64')
        self.embedding_concurrency = config.get('embeddingConcurrency', 1)
        if type(self.embedding_concurrency) is not int or not 1 <= self.embedding_concurrency <= 8:
            raise ValueError('Embedding concurrency must be an integer from 1 to 8')
        self.embed, self.engine_factory = embed, engine_factory
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.last_activity = time.monotonic()
        self.background_paused = False
        self.active_queries = 0
        self.scan_lock = threading.Lock()
        self.scan_cache = {}
        self.source_cache = {}
        self.feature_cache = {}
        self.last_full_scan = 0
        self.strict_freshness = config.get('strictFreshness', sys.platform == 'win32')
        self.limits = {'files': config.get('maxFiles', 50000), 'bytes': config.get('maxSourceBytes', 256*1024*1024)}
        self.exclude = config.get('exclude', [])
        if not isinstance(self.exclude, list) or any(not isinstance(p, str) for p in self.exclude):
            raise ValueError('Exclusions must be a list of glob patterns')
        if any(type(v) is not int or v < 1 for v in self.limits.values()):
            raise ValueError('Invalid source limits')
        self.generation = None
        self.saved_info = None
        self.building = False
        self.error = None
        self.phase = 'starting'
        self.progress = None
        self.parse_cache = {}
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_units = int(config.get('maxUnits', 200000))
        self.max_vector_bytes = int(config.get('maxVectorBytes', 2*1024**3))
        self.cache_bytes = int(config.get('vectorCacheBytes', 4*1024**3))
        if min(self.max_units, self.max_vector_bytes, self.cache_bytes) < 1 or self.cache_bytes < self.max_vector_bytes:
            raise ValueError('Invalid vector resource budgets')
        self.lock_file = acquire_writer_lock(self.state/'writer.lock')
        self.vector_store = VectorStore(self.state, self.dimensions, self.cache_bytes)
        self.unit_store = UnitStore(self.state)
        self.thread = threading.Thread(target=self._run, name='repository-index', daemon=True)

    def scan(self, *, fresh=False):
        with self.scan_lock:
            full = (fresh and self.strict_freshness) or time.monotonic()-self.last_full_scan >= 60
            if full:
                self.scan_cache.clear()
            snapshot = discover_snapshot(self.root, cache=self.scan_cache, limits=self.limits, exclude=self.exclude)
            if full:
                self.last_full_scan = time.monotonic()
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
        self.wake_event.set()
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
                    'generation': self.generation.info if self.generation else self.saved_info,
                    'error': self.error, 'pollSeconds': self.poll,
                    'backgroundPaused': self.background_paused,
                    'progress': dict(self.progress) if self.progress else None}

    def enter_query(self):
        with self.condition:
            self.active_queries += 1
            self.last_activity = time.monotonic()
        self.wake_event.set()

    def leave_query(self):
        with self.condition:
            self.active_queries -= 1
            self.last_activity = time.monotonic()

    def _progress(self, stage, **counts):
        with self.condition:
            self.progress = {'stage': stage, **counts}

    def current(self, timeout=30):
        deadline = time.monotonic() + timeout
        target, waited = None, False
        while not self.stop_event.is_set():
            check()
            with self.condition:
                self.last_activity = time.monotonic()
            if target is None:
                try:
                    target = self.identity(self.scan(fresh=True))
                except (OSError, ValueError) as error:
                    raise IndexUnavailable('Cannot read current source: ' + str(error)) from None
                self.wake_event.set()
            with self.condition:
                generation = self.generation
                if generation and generation.identity == target:
                    if not waited:
                        return generation
                elif self.error and self.error['identity'] == target:
                    raise IndexUnavailable('Index update failed: ' + self.error['type'])
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise IndexUnavailable('Index is updating; search has not run yet', code='INDEX_UPDATING')
                    self.condition.wait(min(remaining, .1))
                    waited = True
                    # Recheck only when a different generation is published, not on every timer tick.
                    if self.generation and self.generation is not generation:
                        target = None
                    continue
            target = None
            waited = False
        raise IndexUnavailable('Index is stopping')

    def verify(self, generation):
        check()
        try:
            current = self.identity(self.scan(fresh=True)) == generation.identity
        except (OSError, ValueError):
            current = False
        if not current:
            raise IndexUnavailable('Source changed during search; retry for current code')

    def _engine(self, units, vectors):
        if not units:
            return None
        return self.engine_factory(units, vectors, self.config['embeddingUrl'],
                                   self.config['reranker'], self.config.get('embeddingKey', 'local-only'),
                                   embedding_model=self.embedding['model'], feature_cache=self.feature_cache)

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
            if (folder/'unit-shards.json').exists():
                units = self.unit_store.load(json.loads((folder/'unit-shards.json').read_text()))
                vectors = self.vector_store.matrix(json.loads((folder/'vector-refs.json').read_text()))
                vectors.validate()
            else:
                # Old generations remain readable; the next update migrates cached vectors.
                units = json.loads((folder/'units.json').read_text())
                vectors = np.load(folder/'vectors.npy', mmap_mode='r', allow_pickle=False)
                if vectors.shape != (len(units), self.dimensions):
                    return None
                for offset in range(0,len(vectors),64):
                    check()
                    if not np.isfinite(vectors[offset:offset+64]).all():
                        return None
            if vectors.shape != (len(units), self.dimensions):
                return None
            if len(units) > self.max_units or len(units)*self.dimensions*4 > self.max_vector_bytes:
                raise ValueError('Saved index exceeds configured resource limits')
            return Generation(identity, snapshot, info, self._engine(units, vectors))
        except (OSError, ValueError, KeyError):
            return None

    def _embed_batch(self, batch):
        result = self.embed(self.config['embeddingUrl']+'/embeddings',
            {'model': self.embedding['model'], 'input': [text for _, text in batch]},
            self.config.get('embeddingKey', 'local-only'), timeout=60)
        rows = sorted(result['data'], key=lambda row: row['index'])
        if [row['index'] for row in rows] != list(range(len(batch))):
            raise ValueError('Invalid embedding response indices')
        matrix = np.asarray([row['embedding'] for row in rows], dtype=np.float32)
        if matrix.shape != (len(batch), self.dimensions) or not np.isfinite(matrix).all():
            raise ValueError('Invalid embedding vectors')
        return matrix

    def _embed_missing(self, entries, db, vectors):
        batches = iter(entries[offset:offset+self.batch_size]
                       for offset in range(0, len(entries), self.batch_size))
        pending, completed, failure = {}, 0, None
        with ThreadPoolExecutor(max_workers=self.embedding_concurrency,
                                thread_name_prefix='index-embedding') as executor:
            while True:
                # Bound submitted work, not just the number of running threads.
                if self.stop_event.is_set() and failure is None:
                    failure = SourceChanged()
                while failure is None and len(pending) < self.embedding_concurrency:
                    batch = next(batches, None)
                    if batch is None:
                        break
                    pending[submit(executor, self._embed_batch, batch)] = batch
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    batch = pending.pop(future)
                    if future.cancelled():
                        continue
                    try:
                        matrix = future.result()
                    except Exception as error:
                        if failure is None:
                            failure = error
                        continue
                    # Only the coordinator writes SQLite and updates progress.
                    vectors.update(self.vector_store.put(db, [key for key,_ in batch], matrix))
                    completed += len(batch)
                    self._progress('embedding', completedDocuments=completed, totalDocuments=len(entries))
                if failure is not None or self.stop_event.is_set():
                    # Drain running calls so their successful results survive a retry.
                    for future in pending:
                        future.cancel()
        if failure is not None:
            raise failure

    def _build(self, snapshot, identity):
        start = time.monotonic()
        self._progress('parsing', files=len(snapshot['files']))
        report = {}
        units = source_units(self.root, snapshot['files'], language_options=self.options,
                             cache=self.parse_cache, sources_cache=self.source_cache, report=report)
        documents = [document(unit) for unit in units]
        keys = [digest([self.embedding, text]) for text in documents]
        if len(units) > self.max_units or len(units)*self.dimensions*4 > self.max_vector_bytes:
            raise ValueError('Index unit or vector size limit exceeded; narrow the indexed scope')
        missing = {}
        with closing(self.vector_store.open()) as db:
            vectors = self.vector_store.lookup(db, keys)
            missing = {key:text for key,text in zip(keys,documents) if key not in vectors}
            entries = list(missing.items())
            self._progress('embedding', completedDocuments=0, totalDocuments=len(entries))
            self._embed_missing(entries, db, vectors)
        self._progress('finalizing')
        references = [vectors[key] for key in keys]
        matrix = self.vector_store.matrix(references)
        engine = self._engine(units, matrix)
        if self.stop_event.is_set() or self.scan(fresh=True) != snapshot:
            raise SourceChanged()
        previous = {f['path']: f['sha256'] for f in self.generation.snapshot['files']} if self.generation else {}
        now = {f['path']: f['sha256'] for f in snapshot['files']}
        info = {'identity': identity, 'files': len(now), 'units': len(units),
                'embeddedDocuments': len(missing), 'reusedUnits': sum(key not in missing for key in keys),
                'changedFiles': sum(previous.get(path) != sha for path, sha in now.items()),
                'deletedFiles': len(previous.keys() - now.keys()), 'embedding': self.embedding,
                'languageUnits': dict(Counter(unit['language'] for unit in units)),
                'degradedFiles': report['degradedFiles'], 'parseDiagnostics': report['parseDiagnostics'],
                'indexingMs': round((time.monotonic()-start)*1000), 'completedAt': time.time()}
        folder = self.state/('generation-'+uuid.uuid4().hex)
        folder.mkdir(mode=0o700)
        try:
            unit_references = self.unit_store.save(units)
            (folder/'unit-shards.json').write_text(json.dumps(unit_references))
            (folder/'vector-refs.json').write_text(json.dumps(references))
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
                shutil.rmtree(old, ignore_errors=True)
        # Only published generations may trigger reclamation. In-flight engines
        # pin their vector shards; source units are already owned in memory.
        try:
            self.vector_store.collect(references)
            self.unit_store.collect(unit_references)
        except (OSError, sqlite3.Error):
            pass  # A cleanup failure must not invalidate an atomic publication.
        return Generation(identity, snapshot, info, engine)

    def _run(self):
        failed_identity, retry_at, failures = None, 0, 0
        try:
            while not self.stop_event.is_set():
                self.wake_event.clear()
                if self.stop_event.is_set():
                    break
                with self.condition:
                    self.background_paused = not self.active_queries and time.monotonic() - self.last_activity >= self.idle_seconds
                if self.background_paused:
                    # MCP lease renewals and status reads are not search activity.
                    # Keep the generation available without repeatedly reading disk.
                    remaining = self.unload_seconds-(time.monotonic()-self.last_activity)
                    if remaining <= 0:
                        with self.condition:
                            self.generation = None
                            self.parse_cache.clear()
                            self.source_cache.clear()
                            self.feature_cache.clear()
                            self.scan_cache.clear()
                            self.phase = 'sleeping'
                        if self.resident_slot:
                            self.resident_slot.close()
                            self.resident_slot = None
                        self.wake_event.wait()
                    else:
                        self.wake_event.wait(remaining)
                    continue
                identity = None
                try:
                    scan_started = time.monotonic()
                    snapshot = self.scan()
                    identity = self.identity(snapshot)
                    if self.generation and self.generation.identity == identity:
                        with self.condition:
                            self.phase, self.error = 'ready', None
                            self.progress = None
                        # Large trees must not consume a core between requests.
                        # Aim for at most 5% background scan duty, and pause at idle.
                        delay = max(self.poll, (time.monotonic() - scan_started) * 19)
                        remaining = max(0, self.idle_seconds - (time.monotonic() - self.last_activity))
                        self.wake_event.wait(min(delay, remaining))
                        continue
                    if failed_identity == identity and time.monotonic() < retry_at:
                        self.stop_event.wait(self.poll)
                        continue
                    with self.condition:
                        self.phase, self.error = 'updating', None
                        self.progress = {'stage': 'checking', 'files': len(snapshot['files'])}
                    if self.stop_event.wait(self.debounce):
                        break
                    if self.scan() != snapshot:
                        continue
                    if self.resident_slot is None:
                        self._progress('waiting_for_capacity')
                        self.resident_slot = acquire_slot(self.resource_directory, 'resident', self.max_resident, self.stop_event)
                    with build_slot(self.resource_directory, self.max_builds, self.stop_event), RequestScope(
                            timeout=3600, stop=self.stop_event):
                        self.building = True
                        try:
                            generation = self._restore(snapshot, identity) or self._build(snapshot, identity)
                        finally:
                            self.building = False
                    if self.scan(fresh=True) != snapshot:
                        raise SourceChanged()
                    with self.condition:
                        self.generation, self.phase, self.error = generation, 'ready', None
                        self.saved_info = generation.info
                        generation = None  # Do not keep an unloaded engine alive in this loop frame.
                        self.progress = None
                        failed_identity, failures = None, 0
                        self.condition.notify_all()
                except Cancelled:
                    if self.stop_event.is_set():
                        break
                    self._progress('cancelled')
                    self.stop_event.wait(self.poll)
                except SourceChanged:
                    self._progress('source_changed')
                    continue
                except Exception as error:
                    failures = failures+1 if failed_identity == identity else 1
                    backoff = min(60, max(2, self.poll)*2**min(failures-1,5))
                    failed_identity, retry_at = identity, time.monotonic() + backoff
                    with self.condition:
                        self.phase = 'failed'
                        self.error = {'identity': identity, 'type': type(error).__name__, 'retryAfterSeconds': backoff,
                                      'message': str(error) if isinstance(error, ValueError) else type(error).__name__}
                        self.condition.notify_all()
                    self.stop_event.wait(self.poll)
        finally:
            if self.resident_slot:
                self.resident_slot.close()
            self.lock_file.close()

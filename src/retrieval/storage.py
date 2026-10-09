"""Immutable vector and source shards shared across searchable generations."""
from collections import defaultdict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import weakref
import numpy as np
from cancellation import check


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def shard_path(directory, name):
    if not isinstance(name, str) or len(name) != 68 or not name.endswith('.npy') or any(c not in '0123456789abcdef' for c in name[:-4]):
        raise ValueError('Invalid vector shard')
    return directory/name


class VectorMatrix:
    def __init__(self, directory, references, dimensions):
        self.directory = directory
        self.references = references
        self.shape = (len(references), dimensions)
        groups = defaultdict(list)
        for index, (name, row) in enumerate(references):
            shard_path(directory, name)
            if type(row) is not int or row < 0:
                raise ValueError('Invalid vector offset')
            groups[name].append((index, row))
        self.groups = {name: np.asarray(rows, dtype=np.int64) for name, rows in groups.items()}

    def validate(self):
        for name, rows in self.groups.items():
            check()
            values = np.load(shard_path(self.directory, name), mmap_mode='r', allow_pickle=False)
            try:
                if values.dtype != np.float32 or values.ndim != 2 or not 1 <= len(values) <= 64 or values.shape[1] != self.shape[1] or rows[:,1].max() >= len(values) or not np.isfinite(values).all():
                    raise ValueError('Invalid vector shard contents')
            finally:
                values._mmap.close()

    def __matmul__(self, query):
        result = np.empty((self.shape[0], *query.shape[1:]), dtype=np.float32)
        for name, rows in self.groups.items():
            check()
            values = np.load(shard_path(self.directory, name), mmap_mode='r', allow_pickle=False)
            try:
                # Shards contain at most 64 rows; temporary allocations are bounded.
                result[rows[:,0]] = values[rows[:,1]] @ query
            finally:
                values._mmap.close()
        return result


class VectorStore:
    def __init__(self, state, dimensions, budget):
        self.state, self.dimensions, self.budget = state, dimensions, budget
        self.directory = state/'vector-shards'
        self.directory.mkdir(exist_ok=True)
        for temporary in self.directory.glob('*.tmp'):
            temporary.unlink(missing_ok=True)
        self.pins = weakref.WeakSet()
        self.validated = {}

    def open(self):
        db = sqlite3.connect(self.state/'embeddings.sqlite')
        db.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value BLOB NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS vector_locations (key TEXT PRIMARY KEY, shard TEXT NOT NULL, row INTEGER NOT NULL, dimensions INTEGER NOT NULL, used REAL NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS vector_shard ON vector_locations(shard)')
        return db

    def put(self, db, keys, matrix):
        name = fingerprint([keys, hashlib.sha256(matrix.tobytes()).hexdigest()])+'.npy'
        path = shard_path(self.directory, name)
        temporary = path.with_suffix('.tmp')
        with temporary.open('wb') as file:
            np.save(file, matrix, allow_pickle=False)
        temporary.replace(path)
        now = time.time()
        db.executemany('INSERT OR REPLACE INTO vectors VALUES (?, ?)', [(key,b'') for key in keys])
        db.executemany('INSERT OR REPLACE INTO vector_locations VALUES (?, ?, ?, ?, ?)',
                       [(key,name,row,self.dimensions,now) for row,key in enumerate(keys)])
        db.commit()
        return {key:[name,row] for row,key in enumerate(keys)}

    def lookup(self, db, keys):
        wanted = set(keys)
        result = {key:[name,row] for key,name,row in db.execute(
            'SELECT key, shard, row FROM vector_locations WHERE dimensions=?', (self.dimensions,)) if key in wanted}
        valid, by_shard = set(), defaultdict(list)
        for name,row in result.values():
            by_shard[name].append(row)
        for name,rows in by_shard.items():
            path = shard_path(self.directory,name)
            try:
                stat = path.stat()
                signature = (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
                if self.validated.get(name) != signature:
                    candidate = VectorMatrix(self.directory, [[name,row] for row in rows], self.dimensions)
                    candidate.validate()
                    self.validated[name] = signature
                valid.add(name)
            except (OSError,ValueError):
                pass
        result = {key:ref for key,ref in result.items() if ref[0] in valid}
        # Import old blob caches in bounded batches, without re-embedding.
        pending, values = [], []
        for key in wanted-result.keys():
            check()
            row = db.execute('SELECT value FROM vectors WHERE key=?', (key,)).fetchone()
            if row and len(row[0]) == self.dimensions*4:
                vector = np.frombuffer(row[0], dtype=np.float32)
                if np.isfinite(vector).all():
                    pending.append(key); values.append(vector)
            if len(pending) == 64:
                result.update(self.put(db,pending,np.asarray(values))); pending,values=[],[]
        if pending:
            result.update(self.put(db,pending,np.asarray(values)))
        db.executemany('UPDATE vector_locations SET used=? WHERE key=?', [(time.time(),key) for key in result])
        db.commit()
        return result

    def matrix(self, references):
        result = VectorMatrix(self.directory,references,self.dimensions)
        self.pins.add(result)
        return result

    def collect(self, current_references):
        protected = {name for name,row in current_references}
        for matrix in list(self.pins):
            protected.update(matrix.groups)
        with closing(self.open()) as db:
            sizes = {path.name:path.stat().st_size for path in self.directory.glob('*.npy')}
            legacy = db.execute('SELECT coalesce(sum(length(value)),0) FROM vectors').fetchone()[0]
            total = sum(sizes.values())+legacy
            known = set()
            for name,used in db.execute('SELECT shard, max(used) FROM vector_locations GROUP BY shard ORDER BY max(used)').fetchall():
                known.add(name)
                if total <= self.budget or name in protected:
                    continue
                db.execute('DELETE FROM vectors WHERE key IN (SELECT key FROM vector_locations WHERE shard=?)',(name,))
                db.execute('DELETE FROM vector_locations WHERE shard=?',(name,))
                shard_path(self.directory,name).unlink(missing_ok=True)
                self.validated.pop(name, None)
                total -= sizes.get(name,0)
            if total > self.budget and legacy:
                # Legacy entries have no recency information. Current vectors have
                # already migrated, so dropping remaining old blobs is safe.
                db.execute("DELETE FROM vectors WHERE length(value)>0")
            for name in sizes.keys()-known-protected:
                shard_path(self.directory,name).unlink(missing_ok=True)
                self.validated.pop(name, None)
            db.commit()
            # Reclaim legacy blob pages once migration leaves a mostly empty DB.
            pages = db.execute('PRAGMA page_count').fetchone()[0]
            free = db.execute('PRAGMA freelist_count').fetchone()[0]
            if free > 16384 and free > pages//2:
                db.execute('VACUUM')


class UnitStore:
    def __init__(self, state):
        self.directory = state/'unit-shards'
        self.directory.mkdir(exist_ok=True)
        for temporary in self.directory.glob('*.tmp'):
            temporary.unlink(missing_ok=True)

    def save(self, units):
        keys = [fingerprint([u['path'],u['start'],u['end'],u['symbol'],u['text']]) for u in units]
        buckets = defaultdict(list)
        records = {}
        for unit,key in zip(units,keys):
            check()
            relations = [{**r,'target':keys[r['target']]} for r in unit['relations']]
            identity = fingerprint([key,relations,unit['language'],unit['kind'],unit['scope'],unit['owner'],unit['name']])
            bucket = hashlib.sha256(unit['path'].encode()).hexdigest()[:2]
            buckets[bucket].append(identity)
            records[identity] = (unit,key,relations)
        references = []
        for bucket,identities in sorted(buckets.items()):
            name = fingerprint(identities)+'.json'
            path = self.directory/name
            if not path.exists():
                data = []
                for identity in identities:
                    unit,key,relations = records[identity]
                    data.append({**unit,'id':key,'relations':relations,'edges':[]})
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(data,ensure_ascii=False))
                temporary.replace(path)
            references.append(name)
        return references

    def load(self, references):
        units = []
        for name in references:
            if not isinstance(name,str) or len(name)!=69 or not name.endswith('.json') or any(c not in '0123456789abcdef' for c in name[:-5]):
                raise ValueError('Invalid source shard')
            units.extend(json.loads((self.directory/name).read_text()))
        units.sort(key=lambda u:(u['path'],u['start']))
        remap = {u['id']:i for i,u in enumerate(units)}
        if len(remap)!=len(units):
            raise ValueError('Duplicate source identity')
        for i,unit in enumerate(units):
            unit['id']=i
            for relation in unit['relations']:
                relation['target']=remap[relation['target']]
            unit['edges']=sorted({r['target'] for r in unit['relations']})
        return units

    def collect(self, references):
        keep=set(references)
        for path in self.directory.glob('*.json'):
            if path.name not in keep:
                path.unlink()

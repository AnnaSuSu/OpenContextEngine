"""Authenticated, persistent retrieval worker; model inference stays remote."""
import hashlib
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
from socketserver import TCPServer
import sys
import threading
import time
from urllib.request import urlopen
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'retrieval'))
from evidence import EvidenceEngine, VERSION
from planning import plan_query
from live import LiveIndex, IndexUnavailable
from writer_lock import WriterBusy
from shared_worker import SharedWorker


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # This worker binds a numeric loopback address; reverse DNS is unnecessary.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address



def serve(config):
    initialized = time.monotonic()
    live = LiveIndex(config).start() if config.get('root') else None
    shared = SharedWorker(config) if config.get('shared') and live else None
    state = Path(config['state'])
    if live:
        index, retrieval = None, None
    else:
        units = json.loads((state / 'units.json').read_text())
        index = json.loads((state / 'metadata.json').read_text())
        retrieval = EvidenceEngine(units, np.load(state/'vectors.npy'), config['embeddingUrl'], config['reranker'], config['embeddingKey'])
    health = {'status':'ready','engine':VERSION,'index':index,'queryCache':False,
        'initializationMs':round((time.monotonic()-initialized)*1000),
        'sourceSha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ['src/retrieval/engine.py','src/retrieval/batched.py','src/retrieval/routed.py','src/retrieval/evidence.py','src/retrieval/planning.py','src/retrieval/reranker.py','scripts/retrieval-server.py',
             'src/retrieval/languages/__init__.py','src/retrieval/languages/schema.py',
             'src/retrieval/languages/text.py','src/retrieval/languages/files.py',
             'src/retrieval/languages/python.py','src/retrieval/languages/python_calls.py','src/retrieval/languages/go.py','src/retrieval/languages/go_ast.go','src/retrieval/languages/go_types.go',
             'src/retrieval/languages/typescript.py',
             'src/retrieval/languages/typescript.mjs','package.json','package-lock.json']
            if name != 'package-lock.json' or (ROOT/name).is_file()}}
    model_base = config['reranker']['baseUrl'].removesuffix('/v1')
    if not live:
        with urlopen(model_base+'/healthz',timeout=10) as response:
            health['reranker'] = json.load(response)
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(16)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data):
            body = json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/healthz':
                return self.reply(200, {'status':'running','engine':VERSION,'mode':'live'} if live else health)
            if self.path == '/status':
                if not secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+config['serviceKey']):
                    return self.reply(401, {'error':'Unauthorized'})
                return self.reply(200, live.status() if live else {'status':'ready','mode':'frozen','generation':index})
            self.reply(404,{'error':'Not found'})

        def do_POST(self):
            if shared and self.path in ('/lease', '/release'):
                if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + config['serviceKey']):
                    return self.reply(401, {'error': 'Unauthorized'})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= 4096:
                        raise ValueError('Invalid body size')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError('Invalid lease')
                except (ValueError, TypeError):
                    return self.reply(422, {'error': 'Invalid lease request'})
                return self.reply(*shared.lease(body, release=self.path == '/release'))
            if self.path!='/search':
                return self.reply(404,{'error':'Not found'})
            if not secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+config['serviceKey']):
                return self.reply(401,{'error':'Unauthorized'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 1<=length<=32768:
                    raise ValueError('Invalid body size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body,dict) or set(body)-{'query','budget','trace','freshnessWaitMs'}:
                    raise ValueError('Unknown fields')
                query,budget = body.get('query'),body.get('budget',8000)
                wait_ms = body.get('freshnessWaitMs', 30000)
                if type(wait_ms) is not int or not 0 <= wait_ms <= 120000:
                    raise ValueError('Invalid freshness wait')
                if not isinstance(query,str) or not query.strip() or len(query)>8192 or type(budget) is not int or not 256<=budget<=8000 or type(body.get('trace',False)) is not bool:
                    raise ValueError('Invalid search input')
            except (ValueError,TypeError):
                return self.reply(422,{'error':'Expected query text and a token budget between 256 and 8000'})
            start = time.monotonic()
            if not slots.acquire(blocking=False):
                return self.reply(429, {'error': 'Retrieval queue is full; retry later'})
            if shared and not shared.enter():
                slots.release()
                return self.reply(503, {'error': 'Worker is stopping'})
            if not lock.acquire(timeout=30):
                slots.release()
                if shared:
                    shared.leave()
                return self.reply(429, {'error': 'Retrieval queue wait exceeded 30 seconds; retry later'})
            try:
                queued = round((time.monotonic()-start)*1000)
                generation = live.current(wait_ms/1000) if live else None
                engine = generation.engine if live else retrieval
                if engine is None:
                    raw,debug = '', {'tokens':0,'elapsedMs':0}
                else:
                    raw,debug = engine.search(plan_query(query),budget=budget)
                if live:
                    live.verify(generation)
                response = {'context':raw,'tokens':debug['tokens'],'engine':VERSION,
                    'retrievalMs':debug['elapsedMs'],'queueMs':queued,
                    'serverElapsedMs':round((time.monotonic()-start)*1000),'queryCache':False,
                    'index': {'mode':'live','identity':generation.identity,'freshness':'verified-after-search',
                              'completedAt':generation.info['completedAt'],
                              'degradedFiles':generation.info.get('degradedFiles', 0)} if live else {'mode':'frozen'}}
                if body.get('trace'):
                    response['diagnostics'] = debug
                self.reply(200,response)
            except IndexUnavailable as error:
                self.reply(503,{'error':str(error),'index':live.status()})
            except Exception as error:
                print(json.dumps({'event':'search-failed','type':type(error).__name__}),flush=True)
                self.reply(502,{'error':'Retrieval or model request failed'})
            finally:
                lock.release()
                slots.release()
                if shared:
                    shared.leave()

    server = LoopbackHTTPServer(('127.0.0.1',config.get('port',23505)),Handler)
    server.daemon_threads = True
    if shared:
        shared.publish(server.server_port)
        shared.monitor(server)
    try:
        print(json.dumps({'listening':f'http://127.0.0.1:{server.server_port}',
                          'health':{'status':'running','mode':'live'} if live else health}),flush=True)
    except OSError as error:
        # Another client may already have attached through discovery when the
        # launcher disappears. Its closed startup pipe must not kill that writer.
        if not shared or error.errno not in (errno.EPIPE, errno.EINVAL):
            raise
    if shared:
        # Shared workers outlive their launching MCP process and its stdio pipes.
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if shared:
            shared.close()
        if live:
            live.close()


if __name__ == '__main__':
    try:
        serve(json.loads(sys.stdin.readline()))
    except Exception as error:
        code = 'INDEX_LOCKED' if isinstance(error, WriterBusy) else 'STARTUP_FAILED'
        # Only known-safe diagnostics cross the startup protocol; never serialize config or keys.
        message = str(error) if isinstance(error, WriterBusy) else type(error).__name__
        print(json.dumps({'startupError': {'code': code, 'message': message}}), flush=True)
        sys.exit(1)

"""Authenticated, persistent retrieval worker; model inference stays remote."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from urllib.request import urlopen
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'retrieval'))
from routed import RoutedEngine, VERSION


def plan_query(query):
    parts = [part.strip() for part in re.split(r'[:：;；，]|,\s+(?=how|which|why|where|what)|\s+and\s+(?=how|which|why|where|what)', query, flags=re.I) if len(part.strip()) > 7]
    facets = parts if 1 < len(parts) <= 4 else [query]
    return {'intent':query,'facets':[{'question':part,'terms':re.findall(r'[A-Za-z][A-Za-z0-9_]*',part)} for part in facets]}


def serve(config):
    initialized = time.monotonic()
    state = Path(config['state'])
    units = json.loads((state / 'units.json').read_text())
    index = json.loads((state / 'metadata.json').read_text())
    retrieval = RoutedEngine(units, np.load(state/'vectors.npy'), config['embeddingUrl'], config['reranker'], config['embeddingKey'])
    health = {'status':'ready','engine':VERSION,'index':index,'queryCache':False,
        'initializationMs':round((time.monotonic()-initialized)*1000),
        'sourceSha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ['src/retrieval/engine.py','src/retrieval/batched.py','src/retrieval/routed.py','scripts/retrieval-server.py',
             'src/retrieval/languages/__init__.py','src/retrieval/languages/schema.py',
             'src/retrieval/languages/text.py','src/retrieval/languages/files.py',
             'src/retrieval/languages/python.py','src/retrieval/languages/typescript.py',
             'src/retrieval/languages/typescript.mjs','package.json','package-lock.json']}}
    model_base = config['reranker']['baseUrl'].removesuffix('/v1')
    with urlopen(model_base+'/healthz',timeout=10) as response:
        health['reranker'] = json.load(response)
    lock = threading.Lock()

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
            self.reply(200,health) if self.path=='/healthz' else self.reply(404,{'error':'Not found'})

        def do_POST(self):
            if self.path!='/search':
                return self.reply(404,{'error':'Not found'})
            if not secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+config['serviceKey']):
                return self.reply(401,{'error':'Unauthorized'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 1<=length<=32768:
                    raise ValueError('Invalid body size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body,dict) or set(body)-{'query','budget','trace'}:
                    raise ValueError('Unknown fields')
                query,budget = body.get('query'),body.get('budget',4000)
                if not isinstance(query,str) or not query.strip() or len(query)>8192 or type(budget) is not int or not 256<=budget<=8000 or type(body.get('trace',False)) is not bool:
                    raise ValueError('Invalid search input')
            except (ValueError,TypeError):
                return self.reply(422,{'error':'Expected query text and a token budget between 256 and 8000'})
            start = time.monotonic()
            if not lock.acquire(timeout=5):
                return self.reply(429,{'error':'Retrieval worker busy'})
            try:
                queued = round((time.monotonic()-start)*1000)
                raw,debug = retrieval.search(plan_query(query),budget=budget)
                response = {'context':raw,'tokens':debug['tokens'],'engine':VERSION,
                    'retrievalMs':debug['elapsedMs'],'queueMs':queued,
                    'serverElapsedMs':round((time.monotonic()-start)*1000),'queryCache':False}
                if body.get('trace'):
                    response['diagnostics'] = debug
                self.reply(200,response)
            except Exception as error:
                print(json.dumps({'event':'search-failed','type':type(error).__name__}),flush=True)
                self.reply(502,{'error':'Retrieval or model request failed'})
            finally:
                lock.release()

    server = ThreadingHTTPServer(('127.0.0.1',config.get('port',23505)),Handler)
    server.daemon_threads = True
    print(json.dumps({'listening':f'http://127.0.0.1:{server.server_port}','health':health}),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    serve(json.loads(sys.stdin.readline()))

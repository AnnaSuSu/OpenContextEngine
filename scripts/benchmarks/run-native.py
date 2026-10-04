"""Pinned native retrieval adapters. Reference answers are never loaded here."""
import hashlib,json,os,select,shutil,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
C=json.loads(sys.stdin.readline()); ROOT=Path(C['root']); OUT=Path(C['run']); SYSTEM=C['system']
BASE=ROOT/'eval'/C['dataset']; snapshot=json.loads((BASE/'snapshot.json').read_text()); queries=json.loads((BASE/'queries.json').read_text())
UP=Path('/root/reponerve-baselines/upstream'); STATE=ROOT/'.pilot-state/method-comparison-v1'/SYSTEM/C['dataset']; CORPUS=STATE/'corpus';CORPUS.mkdir(parents=True,exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
for f in snapshot['files']:
 b=(ROOT/'.pilot-state'/C['dataset']/'corpus'/f['path']).read_bytes()
 if sha(b)!=f['sha256']:raise ValueError('Source fingerprint mismatch')
 target=CORPUS/f['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
for f in BASE.glob('*.json'):
 if not f.name.startswith('answers'):shutil.copyfile(f,OUT/f.name)
versions={'grepai':'eb941fe8072b7a9af87e2604896456ae16a5127d','oce':'da312e1b8a6ece7a239a4c5df880a2f6b967ccc7','claude-context':'6fc318b4e3ce58e2898b00a9c3538ead9e24dee5'}
if SYSTEM in versions:
 actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=UP/SYSTEM,text=True).strip()
 if actual!=versions[SYSTEM]:raise ValueError('Wrong upstream version')
 if subprocess.check_output(['git','diff','HEAD','--','src','packages/core/src'],cwd=UP/SYSTEM):raise ValueError('Modified upstream implementation')
report={'schemaVersion':1,'system':SYSTEM,'datasetId':C['dataset'],'status':'running','results':[],
 'config':{'toolSha':versions.get(SYSTEM),'primaryBudgetTokens':4000,'embedding':'Qwen3-Embedding-4B','dimensions':1024,'embeddingInputLimit':1024,'reranker':'Qwen3-Reranker-4B','queryCache':False,'executionHost':os.uname().nodename,'harnessSha256':sha(Path(__file__).read_bytes()),'sourceFiles':len(snapshot['files'])}}
def save(): (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
def call(path,data=None,port=23541):
 body=None if data is None else json.dumps(data).encode()
 req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=body,headers={'Content-Type':'application/json','Authorization':'Bearer comparison-local'})
 with urllib.request.urlopen(req,timeout=300) as r:return json.load(r)
def blocks(rows):
 out=[]
 for r in rows:
  path=r.get('file_path',r.get('relativePath')); start=r.get('start_line',r.get('startLine'));content=r.get('content')
  if SYSTEM=='grepai':
   header='File: '+path+'\n\n'
   if not content.startswith(header):raise ValueError('Unexpected grepai display header')
   content=content[len(header):]
  if SYSTEM=='claude-context' and isinstance(start,str) and start.isdecimal():start=int(start)
  p=Path(path)
  if p.is_absolute():path=str(p.relative_to(CORPUS))
  if not isinstance(start,int) or start<1 or not isinstance(content,str):raise ValueError('Invalid native span')
  out.append('Path: '+path+'\n'+'\n'.join(f'{start+i}\t{line}' for i,line in enumerate(content.splitlines())))
 return '\n\n'.join(out)+'\n'
def read_native(timeout):
 if not select.select([process.stdout],[],[],timeout)[0]:raise TimeoutError('Native client response deadline')
 line=process.stdout.readline()
 if not line:raise RuntimeError('Native client exited; see service.log')
 return json.loads(line)
process=None;log=None;begin=time.monotonic();save()
try:
 if SYSTEM=='grepai':
  import yaml
  binary='/root/reponerve-baselines/tooling/bin/grepai'
  subprocess.run(['git','init','-q'],cwd=CORPUS,check=True)
  subprocess.run([binary,'init','--yes','--provider','openai','--backend','gob'],cwd=CORPUS,check=True,stdout=subprocess.DEVNULL)
  cfgfile=CORPUS/'.grepai/config.yaml'; cfg=yaml.safe_load(cfgfile.read_text())
  cfg['embedder'].update(provider='openai',model='Qwen3-Embedding-4B',endpoint=C['embeddingUrl'],api_key='local-only',dimensions=1024,parallelism=1,request_timeout_seconds=300)
  cfg['search']['hybrid']['enabled']=True
  cfgfile.write_text(yaml.safe_dump(cfg));report['config']['nativeSearch']={'hybrid':True,'limit':60,'fileDeduplication':cfg['search']['dedup']}
  log=open(OUT/'index.log','w');process=subprocess.Popen([binary,'watch','--no-ui'],cwd=CORPUS,stdout=log,stderr=log)
  deadline=time.monotonic()+3600
  while True:
   text=(OUT/'index.log').read_text()
   if 'Watching for changes...' in text:break
   if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('grepai index did not become ready; see index.log')
   time.sleep(1)
 elif SYSTEM=='opencontextengine':
  import numpy as np,runpy
  sys.path.insert(0,str(ROOT/'src/retrieval'))
  from routed import RoutedEngine
  state=Path('/root/reponerve-baselines/worker/.pilot-state/reponerve/index') if C['dataset']=='django-v1' else Path('/root/reponerve-baselines/expanded-worker/.pilot-state')/C['dataset']/'index'
  units=json.loads((state/'units.json').read_text()); vectors=np.load(state/'vectors.npy')
  engine=RoutedEngine(units,vectors,C['embeddingUrl'],{'baseUrl':C['rerankerUrl'],'apiKey':C['rerankerKey'],'model':'Qwen3-Reranker-4B'},C['embeddingKey'])
  plan=runpy.run_path(str(ROOT/'scripts/retrieval-server.py'))['plan_query']
  report['config'].update(engine='shared-intent-v4',unitsSha256=sha((state/'units.json').read_bytes()),code={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in (ROOT/'src/retrieval').glob('*.py')})
 elif SYSTEM=='oce':
  state=STATE/'data';state.mkdir(parents=True,exist_ok=True)
  env={**os.environ,'API_KEY':'comparison-local','EMBED_ENDPOINT':C['embeddingUrl']+'/embeddings','EMBED_API_KEY':'local-only','EMBED_MODEL':'Qwen3-Embedding-4B','EMBED_DIMENSIONS':'1024','EMBED_MAX_BATCH_SIZE':'8',
    'RERANK_ENABLED':'true','RERANK_ENDPOINT':C['rerankerUrl']+'/rerank','RERANK_API_KEY':C['rerankerKey'],'RERANK_MODEL':'Qwen3-Reranker-4B','MONITORING_ENABLED':'false','LLM_RERANK_ENABLED':'false','RETRIEVAL_INTENT_CLASSIFICATION_ENABLED':'false','RETRIEVAL_QUERY_REWRITE_ENABLED':'false'}
  report['config'].update(optionalLLM=False,monitoring=False)
  log=open(OUT/'service.log','w');process=subprocess.Popen([sys.executable,'-m','oce.cli','serve','--data-dir',str(state),'--host','127.0.0.1','--port','23541'],cwd=STATE,env=env,stdout=log,stderr=log)
  deadline=time.monotonic()+180
  while True:
   try:call('/find-missing',{'mem_object_names':[]});break
   except Exception:
    if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('OCE service startup failed; see service.log')
    time.sleep(1)
  names=[];nonempty_names=[]
  for i in range(0,len(snapshot['files']),20):
   blobs=[{'path':f['path'],'content':(CORPUS/f['path']).read_text()} for f in snapshot['files'][i:i+20]]
   uploaded=call('/batch-upload',{'blobs':blobs})['blob_names']
   if len(uploaded)!=len(blobs):raise RuntimeError('OCE upload count mismatch')
   names+=uploaded
   nonempty_names += [name for name,blob in zip(uploaded,blobs) if blob['content'].strip()]
  deadline=time.monotonic()+3600
  while True:
   status=call('/agents/blob-status',{'blobs':{'added_blobs':nonempty_names}})
   if not status['unknown_blob_names'] and not status['nonindexed_blob_names']:break
   if time.monotonic()>deadline:raise RuntimeError('OCE indexing incomplete')
   time.sleep(2)
  scope={'added_blobs':names};report['indexStatus']={**status,'uploadedFiles':len(names),'nonemptyFilesVerified':len(nonempty_names),'emptyFiles':len(names)-len(nonempty_names)}
 elif SYSTEM=='claude-context':
  log=open(OUT/'service.log','w')
  process=subprocess.Popen(['node',str(ROOT/'scripts/benchmarks/claude-client.cjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,cwd=STATE)
  empty_files=[f['path'] for f in snapshot['files'] if not (CORPUS/f['path']).read_text().strip()]
  report['config']['excludedEmptyFiles']=empty_files
  process.stdin.write(json.dumps({'corpus':str(CORPUS),'embeddingUrl':C['embeddingUrl'],'milvusUrl':'127.0.0.1:19542','emptyFiles':empty_files})+'\n');process.stdin.flush()
  ready=read_native(3600)
  if not ready.get('ready'):raise RuntimeError('Claude Context indexing failed')
  report['indexStatus']=ready
 report['indexingMs']=round((time.monotonic()-begin)*1000);save();print(json.dumps({'system':SYSTEM,'dataset':C['dataset'],'indexReady':True}),flush=True)
 for i,task in enumerate(queries['cases']):
  for language in (['zh','en'] if i%2==0 else ['en','zh']):
   query=task['queries'][language];start=time.monotonic()
   if SYSTEM=='grepai':
    result=subprocess.run([binary,'search',query,'--json','--limit','60'],cwd=CORPUS,capture_output=True,text=True,check=True,timeout=120);native=json.loads(result.stdout);raw=blocks(native)
   elif SYSTEM=='opencontextengine': raw,native=engine.search(plan(query),budget=4000)
   elif SYSTEM=='oce': native=call('/agents/codebase-retrieval',{'information_request':query,'blobs':scope});raw=native['formatted_retrieval']
   else:
    process.stdin.write(json.dumps({'query':query})+'\n');process.stdin.flush();native=read_native(120);raw=blocks(native['results'])
   elapsed=round((time.monotonic()-start)*1000);stem=f'{task["id"]}.{language}'
   (OUT/(stem+'.native.json')).write_text(json.dumps(native,ensure_ascii=False,indent=2)+'\n');(OUT/(stem+'.txt')).write_text(raw)
   report['results'].append({'id':task['id'],'language':language,'query':query,'status':'completed','rawFile':stem+'.txt','nativeFile':stem+'.native.json','sha256':sha(raw.encode()),'elapsedMs':elapsed})
   save();print(json.dumps({'system':SYSTEM,'dataset':C['dataset'],'completed':len(report['results']),'elapsedMs':elapsed}),flush=True)
 report['status']='completed'
except Exception as exc:
 report['status']='failed';report['error']=f'{type(exc).__name__}: {exc}'.replace(C['rerankerKey'],'[REDACTED]')[:600]
 print(json.dumps({'system':SYSTEM,'status':'failed','error':report['error']}),flush=True);raise
finally:
 if process:
  process.terminate()
  try:process.wait(timeout=10)
  except subprocess.TimeoutExpired:process.kill()
 if log:log.close()
 report['elapsedMs']=round((time.monotonic()-begin)*1000);save()

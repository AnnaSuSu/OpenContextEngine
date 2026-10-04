"""Read-only audit of the comparison host's native persistent indexes."""
import hashlib,json,sqlite3
from pathlib import Path
from pymilvus import MilvusClient
ROOT=Path('/root/reponerve-baselines/comparison-worker')
client=MilvusClient(uri='http://127.0.0.1:19542')
result={'schemaVersion':1,'claudeContext':[]}
for dataset in ['django-v1','expanded-v1/click','expanded-v1/httpx','expanded-v1/zod']:
 corpus=ROOT/'.pilot-state/method-comparison-v1/claude-context'/dataset/'corpus'
 snapshot=json.loads((ROOT/'eval'/dataset/'snapshot.json').read_text())
 expected={f['path'] for f in snapshot['files'] if (corpus/f['path']).read_text().strip()}
 collection='hybrid_code_chunks_'+hashlib.md5(str(corpus).encode()).hexdigest()[:8]
 stored=client.query(collection_name=collection,filter='',output_fields=['count(*)'])[0]['count(*)']
 iterator=client.query_iterator(collection_name=collection,batch_size=1000,filter='',output_fields=['id','relativePath'])
 found=set();ids=set();count=0
 try:
  while True:
   rows=iterator.next()
   if not rows:break
   count+=len(rows);found.update(r['relativePath'] for r in rows);ids.update(r['id'] for r in rows)
 finally:iterator.close()
 missing=sorted(expected-found)
 reports=[json.loads(p.read_text()) for p in sorted((ROOT/'runs').glob('claude-context-*/report.json'))]
 native=next(r for r in reversed(reports) if r['status']=='completed' and r['datasetId']==dataset)
 if missing or count!=len(ids) or count>stored or stored!=native['indexStatus']['totalChunks']:raise ValueError(f'{dataset}: missing files or count mismatch: {missing}')
 result['claudeContext'].append({'dataset':dataset,'nonemptyFiles':len(expected),'reportedEntityCount':stored,'nativeIndexedChunks':native['indexStatus']['totalChunks'],'enumeratedUniqueIds':count,'missingNonemptyFiles':missing})
base=ROOT/'.pilot-state/method-comparison-v1/contextweaver/django-v1'
db=next(base.glob('user-state/.contextweaver/index/*/index.db'))
con=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)
rows=con.execute('SELECT path,content FROM files').fetchall()
found={str(Path(path).relative_to(base/'corpus')) if Path(path).is_absolute() else path:content for path,content in rows}
snapshot=json.loads((ROOT/'eval/django-v1/snapshot.json').read_text())
for file in snapshot['files']:
 if file['path'] not in found:raise ValueError('ContextWeaver missing '+file['path'])
 if hashlib.sha256(found[file['path']].encode()).hexdigest()!=file['sha256']:raise ValueError('ContextWeaver source differs')
large=['django/db/models/query.py','django/db/models/sql/query.py']
result['contextWeaverDjango']={'sourceFilesVerified':len(found),'formerlySkippedFiles':[{'path':p,'characters':len(found[p])} for p in large]}
result['status']='passed'
print(json.dumps(result,indent=2))

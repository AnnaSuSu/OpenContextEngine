"""Verify frozen inputs, remote index identities, and archived raw responses."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sha=lambda data:hashlib.sha256(data).hexdigest()
read=lambda p:json.loads(p.read_text())
engine=read(ROOT/'eval/expanded-v1/engine-freeze.json')
for name,digest in engine['sha256'].items():assert sha((ROOT/name).read_bytes())==digest,name
results=[]
for name in sys.argv[1:]:
 run=Path(name);report=read(run/'report.json');freeze=read(run/'freeze.json');snapshot=read(run/'snapshot.json')
 assert report['status']=='completed' and len(report['results'])==20
 for file,digest in freeze['sha256'].items():assert sha((run/file).read_bytes())==digest
 for file in snapshot['files']:assert sha((ROOT/'.pilot-state'/report['datasetId']/'corpus'/file['path']).read_bytes())==file['sha256']
 pairs=set()
 for row in report['results']:
  assert row['status']=='completed' and sha((run/row['rawFile']).read_bytes())==row['sha256']
  pairs.add((row['id'],row['language']))
 assert len(pairs)==20
 if report['system']=='reponerve-service':
  h=report['config']['workerHealth'];i=h['index']
  assert i['identity']==sha((i['version']+json.dumps(snapshot,sort_keys=True)+json.dumps(i['languageAdapters'],sort_keys=True)).encode())
  assert all(engine['sha256'][name]==digest for name,digest in h['sourceSha256'].items())
  assert h['reranker']['max_batch_size']==32 and h['reranker']['batch_token_budget']==8192
  for row in report['results']:
   native=read(run/row['nativeFile']);assert native['queryCache']==False and native['tokens']<=4000
 results.append({'run':str(run),'queries':20,'verified':True})
assert len(results)==6
print(json.dumps({'engineUnchanged':True,'rawAndInputsVerified':True,'queries':sum(r['queries'] for r in results),'runs':results},indent=2))

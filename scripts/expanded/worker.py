"""Index frozen public corpora and serve the unchanged retrieval engine per corpus."""
import json,signal,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/retrieval'))
from engine import build_index
config=json.loads(sys.stdin.readline())
children=[]
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
try:
 for item in config['datasets']:
  snapshot=json.loads(Path(item['snapshot']).read_text())
  _,_,info=build_index(item['corpus'],snapshot,item['state'],config['embeddingIndexUrl'])
  Path(item['state'],'build-report.json').write_text(json.dumps(info,indent=2)+'\n')
  child=subprocess.Popen([sys.executable,str(ROOT/'scripts/retrieval-server.py')],stdin=subprocess.PIPE)
  child.stdin.write((json.dumps({'state':item['state'],'serviceKey':config['serviceKey'],'port':item['port'],
    'embeddingUrl':config['embeddingQueryUrl'],'embeddingKey':config['embeddingKey'],'reranker':config['reranker']})+'\n').encode())
  child.stdin.close();children.append(child)
  print(json.dumps({'indexed':item['name'],'info':info,'port':item['port']}),flush=True)
 print(json.dumps({'allIndexed':True}),flush=True)
 for child in children:
  if child.wait()!=0:raise RuntimeError('Retrieval child exited')
finally:
 for child in children:
  if child.poll() is None:child.terminate()

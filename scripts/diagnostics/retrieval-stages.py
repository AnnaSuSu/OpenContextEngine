"""Capture frozen retrieval intermediates; no gold labels or selection changes."""
import hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/retrieval'))
import batched
config=json.loads(sys.stdin.readline())
source=(ROOT/'src/retrieval/batched.py').read_text()
assert hashlib.sha256(source.encode()).hexdigest()=='914f7879dc8ae07f3971d82a948f8103ac25046d52e566b94505888be684fdeb'
anchor='        return raw,'
assert source.count(anchor)==1
capture="""        self.stage_trace = {
            'queries': queries, 'dense': dense.tolist(), 'pools': pools,
            'lexical': [self.lexical(q + (' ' + ' '.join(facets[c-1]['terms']) if c else '')).tolist() for c,q in enumerate(queries)],
            'fused': dict(fused), 'seeds': sorted(seeds), 'expanded': sorted(expanded),
            'candidates': sorted(candidates), 'rankedBeforeRetention': ranked, 'retained': retained,
            'pairScores': [{'query':q,'uid':uid,'score':score} for (q,uid),score in pair_cache.items()],
            'facetScores': facet_scores, 'overall': overall, 'costs': self.costs, 'selected': selected,
        }
"""
namespace=dict(batched.__dict__)
original=batched.post
calls=0
def bounded_post(*args,**kwargs):
 global calls
 calls+=1
 if calls>12:raise RuntimeError('Diagnostic model request cap exceeded')
 return original(*args,**{**kwargs,'timeout':60})
exec(compile(source.replace(anchor,capture+anchor),'<diagnostic frozen engine>','exec'),namespace)
namespace['post']=bounded_post
spec=importlib.util.spec_from_file_location('retrieval_server',ROOT/'scripts/retrieval-server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
out=ROOT/'.pilot-state/expanded-v1/diagnostics';out.mkdir(exist_ok=True)
for repo in ['zod','httpx']:
 state=ROOT/'.pilot-state/expanded-v1'/repo/'index'
 units=json.loads((state/'units.json').read_text())
 (out/f'{repo}.units.json').write_text(json.dumps(units))
 engine=namespace['BatchedEngine'](units,np.load(state/'vectors.npy'),config['embeddingUrl'],config['reranker'],config['embeddingKey'])
 for task in config['tasks']:
  if task['repo']!=repo:continue
  raw,debug=engine.search(server.plan_query(task['query']),budget=4000)
  name=f"{repo}.{task['id']}.{task['language']}"
  (out/f'{name}.json').write_text(json.dumps({'task':task,'context':raw,'contextSha256':hashlib.sha256(raw.encode()).hexdigest(),'diagnostics':debug,'stages':engine.stage_trace},ensure_ascii=False))
  print(json.dumps({'finished':name,'contextSha256':hashlib.sha256(raw.encode()).hexdigest(),'modelRequestsSoFar':calls}),flush=True)

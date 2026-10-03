"""Compare supported-language units and replay saved v6 outputs without model calls."""
import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/retrieval'))
from languages import source_units
from engine import Engine
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
results=[]
runs={
 'click':'reponerve-v6-regression-click-2026-10-03T16-12-34.807Z',
 'httpx':'reponerve-v6-regression-httpx-2026-10-03T16-14-23.565Z',
 'zod':'reponerve-v6-regression-zod-2026-10-03T16-16-00.747Z',
}
for repo,directory in runs.items():
 snapshot=json.loads((ROOT/f'eval/expanded-v1/{repo}/snapshot.json').read_text())
 previous=ROOT/f'.pilot-state/history-v1/{repo}-index/units.json'
 expected=json.loads(previous.read_text())
 start=time.perf_counter();selection={}
 units=source_units(ROOT/f'.pilot-state/expanded-v1/{repo}/corpus',snapshot['files'],report=selection)
 assert units==expected,repo
 run=ROOT/'runs'/directory
 report=json.loads((run/'report.json').read_text())
 replayed=0
 for row in report['results']:
  assert row['status']=='completed'
  raw=run/row['rawFile'];assert sha(raw)==row['sha256']
  native=json.loads((run/row['nativeFile']).read_text())
  rendered='\n'.join(Engine.render(units[item['id']]) for item in native['diagnostics']['selected'])
  assert rendered==raw.read_text(),(repo,row['id'],row['language'])
  replayed+=1
 results.append({'repository':repo,'files':len(snapshot['files']),'units':len(units),
                 'allFieldsUnchanged':True,'previousUnitsSha256':sha(previous),
                 'replayedOutputs':replayed,'selection':selection,
                 'elapsedMs':round((time.perf_counter()-start)*1000)})
report={'kind':'structural compatibility and deterministic output replay; not new model queries',
        'repositories':results,'units':sum(r['units'] for r in results),
        'replayedOutputs':sum(r['replayedOutputs'] for r in results)}
out=ROOT/'docs/eval/results/text-fallback-compatibility-20261004.json'
out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))

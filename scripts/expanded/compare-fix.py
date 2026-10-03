"""Compare a development regression against preserved expanded-v1 responses."""
import hashlib,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
read=lambda path:json.loads(path.read_text())
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
base=read(ROOT/'docs/eval/results/expanded-comparison-20261003.json')
entries=[];changes=[]
for directory in map(Path,sys.argv[1:]):
 report=read(directory/'report.json');scores=read(directory/'scores.v1.json')
 assert report['status']=='completed' and len(report['results'])==20
 repo=report['datasetId'].split('/')[1];old=next(e for e in base['entries'] if e['repo']==repo and e['system']=='reponerve')
 assert old['answerSha256']==scores['answerSha256'] and old['freeze']==report['freeze']
 assert sha(ROOT/old['run']/'report.json')==old['reportSha256']
 assert sha(ROOT/old['run']/'scores.v1.json')==old['scoresSha256']
 assert report['config']['workerHealth']['index']['identity']==old['indexing']['identity']
 for name,digest in read(directory/'engine-freeze.json')['sha256'].items():assert sha(ROOT/name)==digest
 for name,digest in report['freeze']['sha256'].items():assert sha(directory/name)==digest
 for name,digest in report['config']['workerHealth']['sourceSha256'].items():assert sha(ROOT/name)==digest
 def blank_adjust(score):
  count=score['covered']
  for unit in score['units']:
   if unit['covered']:continue
   if any(all(not (ROOT/'.pilot-state/expanded-v1'/repo/'corpus'/miss['path']).read_text().splitlines()[line-1].strip() for miss in alt['missing'] for line in miss['missingLines']) for alt in unit['alternatives']):count+=1
  return {'coverage':count/score['total'],'complete':count==score['total']}
 for row in scores['rows']:
  oldrow=next(r for r in old['rows'] if r['id']==row['id'] and r['language']==row['language'])
  before=next(s for s in oldrow['budgetScores'] if s['budget']==4000);after=next(s for s in row['budgetScores'] if s['budget']==4000)
  raw=next(r for r in report['results'] if r['id']==row['id'] and r['language']==row['language'])
  assert sha(directory/raw['rawFile'])==raw['sha256']
  native=read(directory/raw['nativeFile']);debug=native['diagnostics']
  assert native['queryCache']==False and native['tokens']<=4000 and debug['rerankedCount']<=80
  assert debug['modelRequests']['embedding']==1 and debug['modelRequests']['rerank']<=2
  assert not set(debug['retention']['core'])&set(debug['retention']['graph'])
  assert len(debug['selected'])==len({r['id'] for r in debug['selected']})
  assert not after['diagnostic']['invalid']
  item={'repo':repo,'id':row['id'],'language':row['language'],'before':{'coverage':before['coverage'],'complete':before['complete'],'elapsedMs':oldrow['elapsedMs'],**{'blankAdjusted':blank_adjust(before)}},'after':{'coverage':after['coverage'],'complete':after['complete'],'elapsedMs':row['elapsedMs'],'blankAdjusted':blank_adjust(after)},'rerankedCount':debug['rerankedCount'],'contextOnlyPieces':sum(x['contextOnly'] for x in debug['selected']),'run':str(directory)}
  entries.append(item)
  if abs(before['coverage']-after['coverage'])>1e-10:changes.append(item)
assert len(entries)==60 and len({(r['repo'],r['id'],r['language']) for r in entries})==60
summaries={}
for repo in ['all','click','httpx','zod']:
 rows=[r for r in entries if repo=='all' or r['repo']==repo];summaries[repo]={}
 for version in ['before','after']:
  vals=[r[version] for r in rows];times=sorted(v['elapsedMs'] for v in vals)
  summaries[repo][version]={'queries':len(vals),'coverage':statistics.mean(v['coverage'] for v in vals),'completeCount':sum(v['complete'] for v in vals),'blankAdjustedCoverage':statistics.mean(v['blankAdjusted']['coverage'] for v in vals),'blankAdjustedCompleteCount':sum(v['blankAdjusted']['complete'] for v in vals),'medianMs':statistics.median(times),'p95Ms':times[math.ceil(len(times)*.95)-1]}
result={'kind':'development-regression-after-failure-analysis','engine':'batched-dag-v6','independentTasks':30,'queries':60,'primaryBudget':4000,'notHeldOut':True,'summary':summaries,'wins':sum(r['after']['coverage']>r['before']['coverage'] for r in entries),'losses':sum(r['after']['coverage']<r['before']['coverage'] for r in entries),'changes':changes,'rows':entries,'validation':{'frozenSourceQueriesAnswersMatched':True,'localAndRemoteEngineHashesMatched':True,'rawResponseHashesMatched':True,'sourceLinesVerified':True,'noDuplicateOutputUnits':True,'rerankMax80':True,'embeddingCalls1':True,'rerankCallsMax2':True,'queryCacheFalse':True,'tokensMax4000':True}}
path=ROOT/'docs/eval/results/candidate-fix-20261004.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'summary':summaries,'wins':result['wins'],'losses':result['losses'],'changes':[{k:r[k] for k in ['repo','id','language','before','after']} for r in changes]},ensure_ascii=False,indent=2))

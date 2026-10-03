import { readFileSync,writeFileSync,mkdirSync } from 'node:fs';
import { resolve,relative } from 'node:path';
import { projectRoot } from '../../src/pilot/config.mjs';
import { sha256 } from '../../src/eval/evidence.mjs';
const dirs=process.argv.slice(2).map(p=>resolve(p));
if(dirs.length!==6)throw Error('Expected six explicit run directories');
const mean=xs=>xs.reduce((a,b)=>a+b,0)/xs.length;
const timing=xs=>{const s=xs.filter(Number.isFinite).sort((a,b)=>a-b),n=s.length;return {samples:n,medianMs:n%2?s[(n-1)/2]:(s[n/2-1]+s[n/2])/2,p95Ms:s[Math.ceil(n*.95)-1],minMs:s[0],maxMs:s[n-1]};};
const entries=dirs.map(directory=>{
 const read=name=>JSON.parse(readFileSync(resolve(directory,name)));
 const report=read('report.json'),scores=read('scores.v1.json');
 return {repo:report.datasetId.split('/')[1],system:report.system==='ace'?'ace':'reponerve',run:relative(projectRoot,directory),status:report.status,commit:report.commit,
  reportSha256:sha256(readFileSync(resolve(directory,'report.json'))),scoresSha256:sha256(readFileSync(resolve(directory,'scores.v1.json'))),answerSha256:scores.answerSha256,freeze:report.freeze,
  indexing:report.indexing??report.config.workerHealth.index,summary:scores.summary,latency:timing(scores.rows.map(r=>r.elapsedMs)),rows:scores.rows};
});
if(new Set(entries.map(e=>e.repo+e.system)).size!==6||entries.some(e=>!['click','httpx','zod'].includes(e.repo)))throw Error('Duplicate or invalid runs');
for(const repo of ['click','httpx','zod']){const pair=entries.filter(e=>e.repo===repo);if(pair[0].answerSha256!==pair[1].answerSha256||JSON.stringify(pair[0].freeze)!==JSON.stringify(pair[1].freeze))throw Error('Unpaired inputs');}
const systems={};
for(const system of ['ace','reponerve']){
 const rows=entries.filter(e=>e.system===system).flatMap(e=>e.rows.map(r=>({...r,repo:e.repo})));
 const summary={};
 for(const budget of [2000,4000,8000]){
  summary[budget]={};
  for(const language of ['zh','en','all']){
   const group=rows.filter(r=>language==='all'||r.language===language),bs=group.map(r=>r.budgetScores.find(s=>s.budget===budget));
   summary[budget][language]={queries:group.length,completed:group.filter(r=>r.status==='completed').length,coverage:mean(bs.map(s=>s.coverage)),completeCount:bs.filter(s=>s.complete).length,completeRecall:mean(bs.map(s=>Number(s.complete))),invalidNumberedLines:bs.reduce((a,s)=>a+s.diagnostic.invalid.length,0)};
  }
 }
 systems[system]={summary,latency:timing(rows.map(r=>r.elapsedMs)),rawTokens:{min:Math.min(...rows.map(r=>r.rawTokens)),max:Math.max(...rows.map(r=>r.rawTokens)),mean:mean(rows.map(r=>r.rawTokens))},rawCoverage:mean(rows.map(r=>r.rawScore.coverage)),rawInvalidNumberedLines:rows.reduce((a,r)=>a+r.rawScore.diagnostic.invalid.length,0)};
}
const paired=entries.filter(e=>e.system==='reponerve').flatMap(e=>e.rows.map(r=>{
 const ace=entries.find(a=>a.repo===e.repo&&a.system==='ace').rows.find(a=>a.id===r.id&&a.language===r.language);
 const score=x=>x.budgetScores.find(s=>s.budget===4000);
 return {repo:e.repo,id:r.id,language:r.language,reponerve:score(r).coverage,ace:score(ace).coverage,delta:score(r).coverage-score(ace).coverage,reponerveMissing:score(r).units.filter(u=>!u.covered).map(u=>({id:u.id,fact:u.fact})),aceMissing:score(ace).units.filter(u=>!u.covered).map(u=>({id:u.id,fact:u.fact}))};
}));
const pairs={wins:paired.filter(p=>p.delta>1e-10).length,ties:paired.filter(p=>Math.abs(p.delta)<=1e-10).length,losses:paired.filter(p=>p.delta< -1e-10).length};
const out={schemaVersion:1,kind:'frozen-cross-repository-comparison',createdAt:new Date().toISOString(),independentTasks:30,queriesPerSystem:60,evidenceUnits:95,primaryBudgetTokens:4000,systems,pairs,paired,entries,
 notes:['Source-derived Codex annotations frozen before retrieval; no independent or hidden-benchmark claim.','Chinese and English are paired variants of 30 tasks, not 60 independent tasks.','One run per query; p95 uses nearest rank, median averages central values.','Latency includes transport from the same Mac; backends and output sizes differ.','Supplemental budgets truncate the same returned text; RepoNerve was requested at 4000 tokens, so 8000 is not a separate 8000-token retrieval run.']};
mkdirSync(resolve(projectRoot,'docs/eval/results'),{recursive:true});
writeFileSync(resolve(projectRoot,'docs/eval/results/expanded-comparison-20261003.json'),JSON.stringify(out,null,2)+'\n');
console.log(JSON.stringify({systems,pairs,repositories:entries.map(({repo,system,status,summary,latency,indexing})=>({repo,system,status,summary:summary[4000],latency,indexing}))},null,2));

// Local, offline scoring. Models and retrieval workers never receive references.
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {sha256,tokenCount,budgetPrefix,validateAnswers,scoreEvidence} from '../../src/eval/evidence.mjs';
import {normalizeGrepai} from './normalize-native.mjs';
const root=resolve(import.meta.dirname,'../..');
const manifest=JSON.parse(readFileSync(resolve(process.argv[2])));
const budgets=[1000,2000,3000,4000];
const median=xs=>{const s=xs.toSorted((a,b)=>a-b);return s.length%2?s[s.length>>1]:(s[s.length/2-1]+s[s.length/2])/2;};
const entries=[];
for(const item of manifest.runs){
 const directory=resolve(root,'runs',item.run),base=resolve(root,'eval',item.dataset);
 const read=name=>JSON.parse(readFileSync(resolve(directory,name)));
 const report=read('report.json');
 for(const name of ['snapshot.json','queries.json']){
  if(sha256(readFileSync(resolve(directory,name)))!==sha256(readFileSync(resolve(base,name))))throw Error('Run input differs from frozen dataset');
 }
 const reportedSystem=report.system??(report.mode==='DirectContext.search'?'ace':null);
 if(reportedSystem!==item.system)throw Error('System identity mismatch');
 const snapshot=JSON.parse(readFileSync(resolve(base,'snapshot.json'))),queries=JSON.parse(readFileSync(resolve(base,'queries.json')));
 const answerFile=item.dataset==='django-v1'?'answers.v2.json':'answers.v1.json';
 const gold=JSON.parse(readFileSync(resolve(base,answerFile)));
 const sourceLines=new Map(snapshot.files.map(file=>{
  const b=readFileSync(resolve(root,'.pilot-state',item.dataset,'corpus',file.path));
  if(sha256(b)!==file.sha256)throw Error('Source fingerprint mismatch');
  return [file.path,b.toString('utf8').replace(/\r\n/g,'\n').split('\n')];
 }));
 validateAnswers(gold.answers,sourceLines);
 const answers=new Map(gold.answers.map(a=>[a.id,a]));
 // Apply the same predeclared blank-line correction to every method.
 const nonblank=answer=>({...answer,units:answer.units.map(unit=>({...unit,alternatives:unit.alternatives.map(alt=>({...alt,allOf:alt.allOf.flatMap(span=>{
  const spans=[];let start=null;
  for(let n=span.startLine;n<=span.endLine+1;n++){
   const present=n<=span.endLine&&sourceLines.get(span.path)[n-1].trim()!=='';
   if(present&&start===null)start=n;
   if(!present&&start!==null){spans.push({...span,startLine:start,endLine:n-1});start=null;}
  }
  if(!spans.length)throw Error('Reference span contains only whitespace');
  return spans;
 })}))}))});
 const rows=[];
 for(const task of queries.cases)for(const language of ['zh','en']){
  const matches=report.results.filter(r=>r.id===task.id&&r.language===language);
  if(matches.length>1)throw Error('Duplicate query result');
  const row=matches[0];let raw='';
  if(row?.status==='completed'){
   raw=readFileSync(resolve(directory,row.rawFile),'utf8');
   if(sha256(raw)!==row.sha256)throw Error('Response fingerprint mismatch');
   if(row.query&&row.query!==task.queries[language])throw Error('Query mismatch');
   if(item.system==='grepai')raw=normalizeGrepai(JSON.parse(readFileSync(resolve(directory,row.nativeFile))),resolve(root,'.pilot-state',item.dataset,'corpus'));
  }
  const answer=answers.get(task.id),corrected=nonblank(answer);
  rows.push({id:task.id,language,status:row?.status??'not-run',elapsedMs:row?.elapsedMs??null,responseSha256:row?.sha256??null,rawTokens:tokenCount(raw),scoredResponseSha256:sha256(raw),
   scores:budgets.map(budget=>{
    const selected=budgetPrefix(raw,budget),scored=scoreEvidence(selected.text,corrected,sourceLines),strict=scoreEvidence(selected.text,answer,sourceLines);
    return {budget,tokens:selected.tokens,coverage:scored.coverage,complete:scored.complete,strictCoverage:strict.coverage,
     invalidNumberedLines:scored.diagnostic.invalid.length,missingUnits:scored.units.filter(u=>!u.covered).map(u=>u.id)};
   })});
 }
 entries.push({...item,status:report.status,reportSha256:sha256(readFileSync(resolve(directory,'report.json'))),
  snapshotSha256:sha256(readFileSync(resolve(base,'snapshot.json'))),queriesSha256:sha256(readFileSync(resolve(base,'queries.json'))),answerSha256:sha256(readFileSync(resolve(base,answerFile))),config:report.config??{sdkVersion:report.sdkVersion},rows});
}
const systems=[...new Set(entries.map(e=>e.system))].map(system=>{
 const runs=entries.filter(e=>e.system===system),rows=runs.flatMap(e=>e.rows);
 if(new Set(runs.map(r=>r.dataset)).size!==runs.length)throw Error('Duplicate system/dataset');
 const timings=rows.filter(r=>r.status==='completed').map(r=>r.elapsedMs);
 return {system,queries:rows.length,completed:rows.filter(r=>r.status==='completed').length,runStatus:runs.every(r=>r.status==='completed')?'completed':'incomplete',
  medianMs:timings.length?median(timings):null,p95Ms:timings.length?timings.toSorted((a,b)=>a-b)[Math.ceil(timings.length*.95)-1]:null,
  points:budgets.map((budget,i)=>({budget,coverage:rows.reduce((s,r)=>s+r.scores[i].coverage,0)/rows.length,strictCoverage:rows.reduce((s,r)=>s+r.scores[i].strictCoverage,0)/rows.length,
   completeCount:rows.filter(r=>r.scores[i].complete).length,invalidNumberedLines:rows.reduce((s,r)=>s+r.scores[i].invalidNumberedLines,0)}))};
});
const output={schemaVersion:1,date:'2026-10-04',kind:'internal-development-method-comparison',protocol:manifest.protocol,
 notes:['Source-derived internal development tasks. Not independent or held out.','Bilingual variants are paired by task.','Coverage requires all nonblank reference lines; strict historical scoring retained alongside.','Token budgets include paths and line numbers. Smaller budgets are offline prefixes of the same responses, never label-guided selection.','Query failures count as zero; failed setup is marked incomplete and must not be ranked as a zero-quality method.'],systems,entries};
mkdirSync(resolve(root,'docs/eval/results'),{recursive:true});
const path=resolve(root,'docs/eval/results/method-comparison-20261004.json');writeFileSync(path,JSON.stringify(output,null,2)+'\n');
console.log(JSON.stringify(systems,null,2));

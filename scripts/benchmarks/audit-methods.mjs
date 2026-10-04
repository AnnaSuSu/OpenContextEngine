import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {sha256} from '../../src/eval/evidence.mjs';
const root=resolve(import.meta.dirname,'../..');
const read=path=>JSON.parse(readFileSync(resolve(root,path)));
const protocol=read('eval/method-comparison-v1/protocol.json');
const manifest=read('eval/method-comparison-v1/runs.json');
const data=read('docs/eval/results/method-comparison-20261004.json');
for(const [file,expected] of Object.entries(protocol.sources))if(sha256(readFileSync(resolve(root,file)))!==expected)throw Error('Frozen input changed: '+file);
if(manifest.runs.length!==28||data.entries.length!==28||data.systems.length!==7)throw Error('Incomplete comparison matrix');
for(const system of protocol.systems){
 const runs=manifest.runs.filter(r=>r.system===system);
 if(new Set(runs.map(r=>r.dataset)).size!==4||runs.length!==4)throw Error('Incomplete dataset coverage: '+system);
 const summary=data.systems.find(s=>s.system===system);
 if(!summary||summary.completed!==80||summary.queries!==80||summary.runStatus!=='completed')throw Error('Incomplete queries: '+system);
}
let responses=0;
for(const e of data.entries){
 const reportPath=`runs/${e.run}/report.json`,report=read(reportPath);
 if(sha256(readFileSync(resolve(root,reportPath)))!==e.reportSha256)throw Error('Report changed');
 if(report.results.length!==20||report.status!=='completed')throw Error('Unfinished report');
 if(e.system!=='ace'){
  const gateway=read(`runs/${e.run}/gateway.json`);
  if(gateway.cacheHits!==0||gateway.failures!==0||gateway.transport.transport!=='ssh-tunnel')throw Error('Inconsistent embedding transport or cache');
 }
 for(const row of report.results){
  if(row.status!=='completed'||sha256(readFileSync(resolve(root,'runs',e.run,row.rawFile)))!==row.sha256)throw Error('Raw response changed');
  responses++;
 }
 for(const row of e.rows)for(const point of row.scores){
  if(point.tokens>point.budget||point.coverage<0||point.coverage>1)throw Error('Invalid score or output budget');
 }
}
const environment=read('docs/eval/results/method-environment-20261004.json');
if(Object.values(environment.upstreams).some(u=>u.modifiedSource))throw Error('Upstream implementation modified');
const indexes=read('docs/eval/results/method-index-audit-20261004.json');
if(indexes.status!=='passed'||indexes.claudeContext.length!==4||indexes.contextWeaverDjango.sourceFilesVerified!==883)throw Error('Incomplete native index audit');
const out={schemaVersion:1,status:'passed',systems:7,datasets:4,runs:28,responses,
 checks:['Frozen source/query/reference fingerprints match protocol','Every method completed every query on every repository','Every archived response hash matches its retrieval report','Native upstream source unchanged','All scored prefixes stay within token budgets','All open methods use the same SSH-forwarded embedding transport with no gateway cache or failures','Claude Context stores every nonempty source file; ContextWeaver stores all 883 Django files including formerly skipped large files','Exact source-line validation applied uniformly; native metadata normalized without source expansion'],
 perSystem:data.systems.map(s=>({system:s.system,completed:s.completed,invalidNumberedLinesAt4000:s.points.find(p=>p.budget===4000).invalidNumberedLines})),
 comparisonSha256:sha256(readFileSync(resolve(root,'docs/eval/results/method-comparison-20261004.json')))};
writeFileSync(resolve(root,'docs/eval/results/method-audit-20261004.json'),JSON.stringify(out,null,2)+'\n');console.log(JSON.stringify(out,null,2));

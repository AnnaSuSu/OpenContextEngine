import { readFileSync,writeFileSync,mkdirSync,copyFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { projectRoot,redact } from '../../src/pilot/config.mjs';
import { sha256 } from '../../src/eval/evidence.mjs';
import { search,clientConfig } from '../../src/client.mjs';

const repo=process.argv[2],ports={click:45009,httpx:45010,zod:45011};
const probe=process.argv[3]==='--probe';
if(!ports[repo]||process.argv.length!==(probe?4:3))throw Error('Usage: node scripts/expanded/regress.mjs click|httpx|zod');
const datasetId=`expanded-v1/${repo}`,base=resolve(projectRoot,'eval',datasetId);
const read=name=>JSON.parse(readFileSync(resolve(base,name)));
const freeze=read('freeze.json'),snapshot=read('snapshot.json');
const engineFreeze=JSON.parse(readFileSync(resolve(projectRoot,'eval/regression-v6/engine-freeze.json')));
for(const [name,hash] of Object.entries(freeze.sha256))if(sha256(readFileSync(resolve(base,name)))!==hash)throw Error(`Frozen input changed: ${name}`);
for(const [name,hash] of Object.entries(engineFreeze.sha256))if(sha256(readFileSync(resolve(projectRoot,name)))!==hash)throw Error(`Frozen engine changed: ${name}`);
for(const file of snapshot.files)if(sha256(readFileSync(resolve(projectRoot,'.pilot-state',datasetId,'corpus',file.path)))!==file.sha256)throw Error(`Corpus changed: ${file.path}`);
const config=clientConfig({...process.env,REPONERVE_BASE_URL:`http://127.0.0.1:${ports[repo]}`});
const health=await(await fetch(`${config.baseUrl}/healthz`,{signal:AbortSignal.timeout(15000)})).json();
if(health.status!=='ready'||health.queryCache!==false||health.engine!==engineFreeze.engine||health.index.files!==snapshot.files.length)throw Error('Worker identity/readiness mismatch');
for(const [name,hash] of Object.entries(health.sourceSha256))if(engineFreeze.sha256[name]!==hash)throw Error(`Remote engine mismatch: ${name}`);
const tasks=read('queries.json').cases.filter(task=>!probe||['safe-parsing','multipart-upload'].includes(task.id)).flatMap((task,i)=>(i%2?['en','zh']:['zh','en']).map(language=>({id:task.id,language,query:task.queries[language]})));
const directory=resolve(projectRoot,'runs',`reponerve-v6-${probe?'probe':'regression'}-${repo}-${new Date().toISOString().replaceAll(':','-')}`);
mkdirSync(directory,{recursive:true,mode:0o700});
for(const name of [...Object.keys(freeze.sha256),'freeze.json'])copyFileSync(resolve(base,name),resolve(directory,name));
copyFileSync(resolve(projectRoot,'eval/regression-v6/engine-freeze.json'),resolve(directory,'engine-freeze.json'));
copyFileSync(resolve(projectRoot,'scripts/expanded/regress.mjs'),resolve(directory,'harness.mjs'));
const report={schemaVersion:1,kind:probe?'development-probe':'development-regression',system:'reponerve-service',datasetId,startedAt:new Date().toISOString(),status:'running',commit:snapshot.commit,freeze,
  config:{primaryBudgetTokens:4000,clientLocation:'user-Mac',transport:'authenticated-SSH-forward',baseUrl:config.baseUrl,queryCache:false,workerHealth:health},results:[]};
const save=()=>writeFileSync(resolve(directory,'report.json'),JSON.stringify(report,null,2)+'\n',{mode:0o600});
save();console.log(JSON.stringify({directory,queries:tasks.length}));
const start=Date.now();
try{
  for(const task of tasks){
    const begin=Date.now();
    try{
      const result=await search(task.query,{trace:true,config});
      if(result.queryCache!==false)throw Error('Unexpected query cache');
      const rawFile=`${task.id}.${task.language}.txt`,nativeFile=`${task.id}.${task.language}.native.json`;
      writeFileSync(resolve(directory,rawFile),result.context);
      writeFileSync(resolve(directory,nativeFile),JSON.stringify(result,null,2)+'\n');
      const row={...task,status:'completed',rawFile,nativeFile,sha256:sha256(result.context),elapsedMs:result.clientElapsedMs,retrievalMs:result.retrievalMs,serverElapsedMs:result.serverElapsedMs};
      report.results.push(row);save();console.log(JSON.stringify({repo,completed:report.results.length,id:row.id,language:row.language,elapsedMs:row.elapsedMs}));
    }catch(error){report.results.push({...task,status:'failed',elapsedMs:Date.now()-begin,error:redact(error.message,[config.apiKey])});save();throw error;}
  }
  report.status='completed';
}catch(error){report.status='failed';report.error=redact(error.message,[config.apiKey]);process.exitCode=1;}
finally{report.elapsedMs=Date.now()-start;save();console.log(JSON.stringify({status:report.status,directory,elapsedMs:report.elapsedMs}));}

import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve,dirname } from 'node:path';
import { projectRoot } from '../src/pilot/config.mjs';
import { sha256 } from '../src/eval/evidence.mjs';
import { search,clientConfig } from '../src/client.mjs';

const config=clientConfig();
const health=await(await fetch(`${config.baseUrl}/healthz`,{signal:AbortSignal.timeout(5000)})).json();
if (health.status!=='ready' || health.queryCache!==false) throw new Error('Worker is not ready or has query caching enabled');
const dataset=resolve(projectRoot,'eval/django-v1');
const tasks=JSON.parse(readFileSync(resolve(dataset,'queries.json'))).cases.flatMap(q=>['zh','en'].map(language=>({id:q.id,language,query:q.queries[language]})));
for(let repeat=1;repeat<=3;repeat++){
  const run=resolve(projectRoot,`runs/reponerve-service-django-${new Date().toISOString().replace(/:/g,'-')}`);mkdirSync(run,{recursive:true});
  for(const name of ['queries.json','snapshot.json','protocol.json','freeze.json','answers.v1.json','answers.v2.json'])copyFileSync(resolve(dataset,name),resolve(run,name));
  for(const name of ['scripts/benchmark-service.mjs','src/client.mjs']){const path=resolve(run,'harness',name);mkdirSync(dirname(path),{recursive:true});copyFileSync(resolve(projectRoot,name),path);}
  const report={schemaVersion:1,kind:'development-pilot',system:'reponerve-service',startedAt:new Date().toISOString(),status:'running',
    config:{engine:health.engine,primaryBudgetTokens:4000,repeat,clientLocation:'user-Mac',transport:'authenticated-SSH-forward',baseUrl:config.baseUrl,queryCache:false,workerHealth:health},results:[]};
  const save=()=>writeFileSync(resolve(run,'report.json'),JSON.stringify(report,null,2)+'\n');save();
  console.log(JSON.stringify({run,repeat}));
  const started=Date.now();
  try{
    // Rotate order between complete paired-query rounds; no cross-query cache.
    const order=[...tasks.slice((repeat-1)*7),...tasks.slice(0,(repeat-1)*7)];
    for(const task of order){
      const result=await search(task.query,{trace:true,config});
      if(result.queryCache!==false)throw new Error('Unexpected query cache');
      const rawFile=`${task.id}.${task.language}.txt`,nativeFile=`${task.id}.${task.language}.native.json`;
      writeFileSync(resolve(run,rawFile),result.context);writeFileSync(resolve(run,nativeFile),JSON.stringify(result,null,2));
      report.results.push({...task,status:'completed',rawFile,nativeFile,sha256:sha256(result.context),elapsedMs:result.clientElapsedMs,
        retrievalMs:result.retrievalMs,serverElapsedMs:result.serverElapsedMs});save();
      console.log(JSON.stringify({repeat,completed:report.results.length,id:task.id,language:task.language,elapsedMs:result.clientElapsedMs}));
    }
    report.status='completed';
  }catch(error){report.status='failed';report.error=error.message;throw error;}
  finally{report.elapsedMs=Date.now()-started;save();}
}

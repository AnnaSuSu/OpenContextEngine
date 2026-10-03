import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {parseEnv} from 'node:util';
import {spawn} from 'node:child_process';
import {projectRoot} from '../../src/pilot/config.mjs';
const env={...parseEnv(readFileSync(resolve(projectRoot,'.env'),'utf8')),...process.env};
const workers=[];
for(const [i,repo] of ['click','httpx','zod'].entries()){
 const worker=spawn('/root/reponerve-baselines/worker/.pilot-state/baselines/cocoindex-venv/bin/python',[resolve(projectRoot,'scripts/retrieval-server.py')],{env:{...process.env,OPENBLAS_NUM_THREADS:'2',OMP_NUM_THREADS:'2'},stdio:['pipe','inherit','inherit']});
 worker.stdin.end(JSON.stringify({state:`/root/reponerve-baselines/expanded-worker/.pilot-state/expanded-v1/${repo}/index`,serviceKey:env.RERANK_API_KEY,port:23509+i,embeddingUrl:'http://127.0.0.1:42002/v1',embeddingKey:env.EMBEDDING_API_KEY,reranker:{baseUrl:'http://127.0.0.1:23504/v1',model:'Qwen3-Reranker-4B',apiKey:env.RERANK_API_KEY}})+'\n');
 workers.push(worker);
 worker.on('exit',code=>{if(code){for(const child of workers)child.kill();process.exitCode=code;}});
}
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>workers.forEach(child=>child.kill(signal)));

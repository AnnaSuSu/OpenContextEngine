import {spawn} from 'node:child_process';
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {parseEnv} from 'node:util';
import {projectRoot} from '../../src/pilot/config.mjs';
import {embeddingTransportConfig,remoteRerankerConfig,rerankerExecutionTransport} from '../../src/eval/remote-models.mjs';
import {normalizeEnvironment} from '../../src/environment.mjs';
const env={...normalizeEnvironment(parseEnv(readFileSync(resolve(projectRoot,'.env'),'utf8'))),...normalizeEnvironment(process.env)};
const transport=embeddingTransportConfig(env),reranker=remoteRerankerConfig(env),runtime=rerankerExecutionTransport(env);
const base=resolve(projectRoot,'.pilot-state/expanded-v1');mkdirSync(base,{recursive:true});
const gateway=spawn(process.execPath,[resolve(projectRoot,'scripts/embedding-gateway.mjs'),resolve(base,'gateway.json')],{env,stdio:['ignore','pipe','inherit']});
let worker;
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{worker?.kill(signal);gateway.kill(signal);});
try{
 const url=await new Promise((ok,fail)=>{let buffer='';const timer=setTimeout(()=>fail(Error('Gateway startup timeout')),10000);
  gateway.once('error',fail);gateway.once('exit',()=>fail(Error('Gateway exited')));gateway.stdout.on('data',d=>{buffer+=d;const line=buffer.split('\n')[0];if(buffer.includes('\n')){const e=JSON.parse(line);if(e.listening){clearTimeout(timer);ok(e.listening);}}});});
 worker=spawn(env.OCE_PYTHON,[resolve(projectRoot,'scripts/expanded/worker.py')],{env:{...process.env,OPENBLAS_NUM_THREADS:'2',OMP_NUM_THREADS:'2'},stdio:['pipe','inherit','inherit']});
 worker.stdin.end(JSON.stringify({datasets:['click','httpx','zod'].map((name,i)=>({name,corpus:resolve(base,name,'corpus'),snapshot:resolve(projectRoot,'eval/expanded-v1',name,'snapshot.json'),state:resolve(base,name,'index'),port:23506+i})),embeddingIndexUrl:url,embeddingQueryUrl:transport.requestBaseUrl,embeddingKey:env.EMBEDDING_API_KEY,serviceKey:env.RERANK_API_KEY,reranker:{...reranker,baseUrl:runtime.requestBaseUrl}})+'\n');
 const code=await new Promise((ok,fail)=>{worker.once('error',fail);worker.once('exit',ok);});if(code)process.exitCode=code;
}finally{gateway.kill('SIGTERM');worker?.kill('SIGTERM');}

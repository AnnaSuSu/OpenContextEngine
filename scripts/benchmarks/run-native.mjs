// Run pinned upstream clients on the already-authorized remote evaluation host.
import {readFileSync,mkdirSync} from 'node:fs';
import {parseEnv} from 'node:util';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
if(process.platform!=='linux') throw Error('Use the authorized remote evaluation host');
const root=resolve(import.meta.dirname,'../..');
const env={...parseEnv(readFileSync(resolve(root,'.env'),'utf8')),...process.env};
const [system,dataset]=process.argv.slice(2);
if(!['grepai','oce','claude-context','opencontextengine'].includes(system))throw Error('Unknown system');
if(!['django-v1','expanded-v1/click','expanded-v1/httpx','expanded-v1/zod'].includes(dataset))throw Error('Unknown dataset');
const run=resolve(root,'runs',`${system}-${dataset.replaceAll('/','-')}-${new Date().toISOString().replaceAll(':','-')}`);
mkdirSync(run,{recursive:true});
const gateway=spawn(process.execPath,[resolve(root,'scripts/benchmarks/embedding-gateway.mjs'),resolve(run,'gateway.json')],{env,stdio:['ignore','pipe','inherit']});
let worker;
try{
 const url=await new Promise((ok,fail)=>{let buffer='';const timer=setTimeout(()=>fail(Error('Gateway timeout')),10000);gateway.once('error',fail);gateway.once('exit',()=>fail(Error('Gateway exited')));gateway.stdout.on('data',b=>{buffer+=b;for(const line of buffer.split('\n')){try{const x=JSON.parse(line);if(x.listening){clearTimeout(timer);ok(x.listening);}}catch{}}});});
 worker=spawn('/root/reponerve-baselines/tooling/oce-py312/bin/python',[resolve(root,'scripts/benchmarks/run-native.py')],{cwd:root,env:{...process.env,PATH:env.PATH,LANG:'en_US.UTF-8',OPENBLAS_NUM_THREADS:'2',OMP_NUM_THREADS:'2'},stdio:['pipe','inherit','inherit']});
 worker.stdin.end(JSON.stringify({root,run,system,dataset,embeddingUrl:url,embeddingKey:'local-only',rerankerUrl:'http://127.0.0.1:23504/v1',rerankerKey:env.RERANK_API_KEY})+'\n');
 const code=await new Promise((ok,fail)=>{worker.once('error',fail);worker.once('exit',ok);});process.exitCode=code||0;
}finally{worker?.kill('SIGTERM');gateway.kill('SIGTERM');}

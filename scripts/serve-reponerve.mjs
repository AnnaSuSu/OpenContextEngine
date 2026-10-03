import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { resolve } from 'node:path';
import { projectRoot } from '../src/pilot/config.mjs';
import { embeddingTransportConfig, remoteRerankerConfig, rerankerExecutionTransport } from '../src/eval/remote-models.mjs';

const env = { ...parseEnv(readFileSync(resolve(projectRoot,'.env'),'utf8')), ...process.env };
const embedding = embeddingTransportConfig(env), reranker = remoteRerankerConfig(env), runtime = rerankerExecutionTransport(env);
const serviceKey = env.REPONERVE_API_KEY || env.RERANK_API_KEY;
if (!serviceKey || serviceKey.length<24) throw new Error('Set a strong REPONERVE_API_KEY or the existing project reranker key');
const child = spawn(resolve(projectRoot,'.pilot-state/baselines/cocoindex-venv/bin/python'),[resolve(projectRoot,'scripts/retrieval-server.py')],
  {cwd:projectRoot,env:{...process.env,OPENBLAS_NUM_THREADS:'2',OMP_NUM_THREADS:'2'},stdio:['pipe','inherit','inherit']});
child.stdin.end(JSON.stringify({state:resolve(projectRoot,'.pilot-state/reponerve/index'),serviceKey,port:23505,
  embeddingUrl:embedding.requestBaseUrl,embeddingKey:env.EMBEDDING_API_KEY,
  reranker:{...reranker,baseUrl:runtime.requestBaseUrl}})+'\n');
process.on('SIGTERM',()=>child.kill('SIGTERM'));
process.on('SIGINT',()=>child.kill('SIGINT'));
child.once('exit',code=>{process.exitCode=code??1;});

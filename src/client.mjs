import { readFileSync, existsSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { resolve } from 'node:path';
import { projectRoot } from './pilot/config.mjs';

export function clientConfig(environment=process.env) {
  const file=resolve(projectRoot,'.env');
  const env={...(existsSync(file)?parseEnv(readFileSync(file,'utf8')):{}),...environment};
  const url=new URL(env.REPONERVE_BASE_URL || 'http://127.0.0.1:45005');
  if (url.username || url.password || url.search || url.hash ||
      !(url.protocol==='https:' || url.protocol==='http:' && url.hostname==='127.0.0.1')) throw new Error('Use HTTPS or an explicit loopback SSH forward');
  const apiKey=env.REPONERVE_API_KEY || env.RERANK_API_KEY;
  if (!apiKey) throw new Error('Set REPONERVE_API_KEY or the existing project reranker key');
  return {baseUrl:url.href.replace(/\/$/,''),apiKey};
}

export async function search(query,{budget=4000,trace=false,config=clientConfig()}={}) {
  const started=performance.now();
  const response=await fetch(`${config.baseUrl}/search`,{method:'POST',redirect:'error',signal:AbortSignal.timeout(15000),
    headers:{'content-type':'application/json',authorization:`Bearer ${config.apiKey}`},body:JSON.stringify({query,budget,trace})});
  if (!response.ok) throw new Error(`Retrieval HTTP ${response.status}`);
  const result=await response.json();
  if (typeof result.context!=='string' || !Number.isFinite(result.retrievalMs)) throw new Error('Invalid retrieval response');
  return {...result,clientElapsedMs:Math.round(performance.now()-started)};
}

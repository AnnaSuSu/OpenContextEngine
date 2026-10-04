import { loadEnvironment } from './config.mjs';

export function clientConfig(environment=process.env) {
  const env=loadEnvironment(environment);
  const url=new URL(env.OCE_BASE_URL || 'http://127.0.0.1:45005');
  if (url.username || url.password || url.search || url.hash ||
      !(url.protocol==='https:' || url.protocol==='http:' && url.hostname==='127.0.0.1')) throw new Error('Use HTTPS or an explicit loopback SSH forward');
  const apiKey=env.OCE_API_KEY || env.RERANK_API_KEY;
  if (!apiKey) throw new Error('Set OCE_API_KEY or the existing project reranker key');
  return {baseUrl:url.href.replace(/\/$/,''),apiKey};
}

export async function search(query,{budget=4000,trace=false,freshnessWaitMs=30000,config=clientConfig(),signal}={}) {
  const started=performance.now();
  const timeout = AbortSignal.timeout(freshnessWaitMs + 30000);
  const response=await fetch(`${config.baseUrl}/search`,{method:'POST',redirect:'error',signal:signal ? AbortSignal.any([signal,timeout]) : timeout,
    headers:{'content-type':'application/json',authorization:`Bearer ${config.apiKey}`},body:JSON.stringify({query,budget,trace,freshnessWaitMs})});
  if (!response.ok) {
    if (response.status === 503) {
      const body = await response.json();
      throw new Error(`Index unavailable: ${body.error || 'update pending'}`);
    }
    throw new Error(`Retrieval HTTP ${response.status}`);
  }
  const result=await response.json();
  if (typeof result.context!=='string' || !Number.isFinite(result.retrievalMs)) throw new Error('Invalid retrieval response');
  return {...result,clientElapsedMs:Math.round(performance.now()-started)};
}

export async function indexStatus({config=clientConfig(),signal}={}) {
  const timeout = AbortSignal.timeout(10000);
  const response = await fetch(`${config.baseUrl}/status`, {redirect:'error',
    signal:signal ? AbortSignal.any([signal,timeout]) : timeout,
    headers:{authorization:`Bearer ${config.apiKey}`}});
  if (!response.ok) throw new Error(`Retrieval HTTP ${response.status}`);
  return response.json();
}

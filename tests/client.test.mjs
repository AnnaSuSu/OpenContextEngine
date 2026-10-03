import test from 'node:test';
import assert from 'node:assert/strict';
import {clientConfig,search} from '../src/client.mjs';

test('Retrieval client permits SSH loopback or HTTPS, rejects credentials and cleartext public endpoints',()=>{
  const env={REPONERVE_API_KEY:'test-key-not-a-real-secret',REPONERVE_BASE_URL:'http://127.0.0.1:45005'};
  assert.equal(clientConfig(env).baseUrl,env.REPONERVE_BASE_URL);
  for(const url of ['http://public.example.com','https://user:pass@example.com','https://example.com?token=x']){
    assert.throws(()=>clientConfig({...env,REPONERVE_BASE_URL:url}));
  }
});

test('Client sends the unchanged query once, rejects redirects and malformed worker output',async()=>{
  const original=globalThis.fetch;
  const config={baseUrl:'http://127.0.0.1:45005',apiKey:'test-only'};
  let calls=0;
  try{
    globalThis.fetch=async(url,options)=>{
      calls++;assert.equal(url,config.baseUrl+'/search');assert.equal(options.redirect,'error');
      assert.equal(JSON.parse(options.body).query,'保存后，在哪里处理失败？');
      return new Response(JSON.stringify({context:'source',retrievalMs:12,queryCache:false}));
    };
    const response=await search('保存后，在哪里处理失败？',{config});
    assert.equal(calls,1);assert.equal(response.queryCache,false);assert.ok(response.clientElapsedMs>=0);
    globalThis.fetch=async()=>new Response(JSON.stringify({context:'source'}));
    await assert.rejects(()=>search('query',{config}),/Invalid retrieval response/);
  }finally{globalThis.fetch=original;}
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {clientConfig,search} from '../src/client.mjs';
import {serviceConfig} from '../src/service.mjs';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('Retrieval client permits SSH loopback or HTTPS, rejects credentials and cleartext public endpoints',t=>{
  const configHome=mkdtempSync(join(tmpdir(),'oce-client-config-'));
  t.after(()=>rmSync(configHome,{recursive:true,force:true}));
  const env={OCE_API_KEY:'test-key-not-a-real-secret',OCE_BASE_URL:'http://127.0.0.1:45005'};
  assert.equal(clientConfig(env).baseUrl,env.OCE_BASE_URL);
  const legacy={REPONERVE_API_KEY:'legacy-test-key',REPONERVE_BASE_URL:'http://127.0.0.1:45006'};
  assert.deepEqual(clientConfig(legacy),{baseUrl:legacy.REPONERVE_BASE_URL,apiKey:legacy.REPONERVE_API_KEY});
  assert.deepEqual(clientConfig({...legacy,...env}),{baseUrl:env.OCE_BASE_URL,apiKey:env.OCE_API_KEY});
  for (const prefix of ['OCE_', 'REPONERVE_']) {
    const settings=serviceConfig({root:'.',state:'/tmp/opencontextengine-config-test'}, {
      OCE_CONFIG_HOME:configHome,
      EMBEDDING_BASE_URL:'https://embedding.example/v1',EMBEDDING_SSH_TUNNEL_URL:'',
      RERANK_BASE_URL:'https://reranker.example/v1',RERANK_REMOTE_RUNTIME_URL:'',
      RERANK_MODEL:'test',RERANK_API_KEY:'test-only',
      OCE_EMBEDDING_BATCH_SIZE:'64',OCE_EMBEDDING_CONCURRENCY:'2',
      OCE_SCAN_IDLE_SECONDS:'45',
      OCE_RERANK_API:'rerank',OCE_RERANK_CONCURRENCY:'3',OCE_RERANK_MAX_DOCUMENTS:'64',
      [prefix+'PYTHON']:'/test/python',[prefix+'GO_BINARY']:'/test/go',
      [prefix+'API_KEY']:'configuration-test-only',[prefix+'POLL_SECONDS']:'2',
    });
    assert.equal(settings.config.embeddingBatchSize,64);
    assert.equal(settings.config.embeddingConcurrency,2);
    assert.equal(settings.python,'/test/python');
    assert.equal(settings.workerEnv.OCE_GO_BINARY,'/test/go');
    assert.equal(settings.config.serviceKey,'configuration-test-only');
    assert.equal(settings.config.pollSeconds,2);
    assert.equal(settings.config.scanIdleSeconds,45);
    assert.equal(settings.config.reranker.api,'rerank');
    assert.equal(settings.config.reranker.concurrency,3);
    assert.equal(settings.config.reranker.maxDocuments,64);
  }
  for(const url of ['http://public.example.com','https://user:pass@example.com','https://example.com?token=x']){
    assert.throws(()=>clientConfig({...env,OCE_BASE_URL:url}));
  }
});

test('Client sends the unchanged query once, rejects redirects and malformed worker output',async()=>{
  const original=globalThis.fetch;
  const config={baseUrl:'http://127.0.0.1:45005',apiKey:'test-only'};
  let calls=0;const budgets=[];
  try{
    globalThis.fetch=async(url,options)=>{
      calls++;budgets.push(JSON.parse(options.body).budget);assert.equal(url,config.baseUrl+'/search');assert.equal(options.redirect,'error');
      assert.equal(JSON.parse(options.body).query,'保存后，在哪里处理失败？');
      return new Response(JSON.stringify({context:'source',retrievalMs:12,queryCache:false}));
    };
    const response=await search('保存后，在哪里处理失败？',{config});
    assert.equal(calls,1);assert.equal(response.queryCache,false);assert.ok(response.clientElapsedMs>=0);
    await search('保存后，在哪里处理失败？',{config,budget:4000});
    assert.deepEqual(budgets,[8000,4000]);
    globalThis.fetch=async()=>new Response(JSON.stringify({context:'source'}));
    await assert.rejects(()=>search('query',{config}),/Invalid retrieval response/);
    globalThis.fetch=async()=>new Response(JSON.stringify({error:'Retrieval queue is full; retry later'}),{status:429});
    await assert.rejects(()=>search('query',{config}),/Retrieval busy: Retrieval queue is full; retry later/);
  }finally{globalThis.fetch=original;}
});

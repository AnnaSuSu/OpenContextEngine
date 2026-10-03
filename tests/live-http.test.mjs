import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { startService } from '../src/service.mjs';
import { search, indexStatus } from '../src/client.mjs';

const python = process.env.REPONERVE_PYTHON || ['.venv/bin/python',
  '.pilot-state/language-adapters-venv/bin/python','.pilot-state/baselines/cocoindex-venv/bin/python']
  .map(path => resolve(path)).find(existsSync);

// A deterministic protocol fixture, not a local model or retrieval quality test.
export async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'reponerve-http-'));
  const root = join(dir,'repo');
  await mkdir(root);
  const hooks = {rerank:null, embedding:null};
  const models = createServer(async (request,response) => {
    try {
      let data = '';
      for await (const chunk of request) data += chunk;
      const body = JSON.parse(data);
      let result;
      if (request.url === '/v1/embeddings') {
        if (hooks.embedding) await hooks.embedding(body);
        result = {data:body.input.map((_,index) => ({index,embedding:[1,...Array(1023).fill(0)]}))};
      } else if (request.url === '/v1/rerank-batch') {
        if (hooks.rerank) await hooks.rerank(body);
        result = {results:body.pairs.map(([query_index,document_index],index) =>
          ({index,query_index,document_index,relevance_score:.95}))};
      } else throw new Error('Unexpected path');
      response.writeHead(200,{'content-type':'application/json'});
      response.end(JSON.stringify(result));
    } catch {
      response.writeHead(502).end('{}');
    }
  });
  await new Promise(resolveListen => models.listen(0,'127.0.0.1',resolveListen));
  const modelUrl = `http://127.0.0.1:${models.address().port}/v1`;
  const worker = startService({python,config:{root,state:join(dir,'state'),port:0,
    serviceKey:'test-only-at-least-24-characters',embeddingUrl:modelUrl,
    embeddingIdentity:'https://test-model.invalid/v1',embeddingKey:'test-only',
    reranker:{baseUrl:modelUrl,model:'fixture',apiKey:'test-only'},pollSeconds:.05,debounceSeconds:0}},
    {log:() => {}});
  t.after(async () => {
    await worker.close();
    models.closeAllConnections();
    await new Promise(resolveClose => models.close(resolveClose));
    await rm(dir,{recursive:true,force:true});
  });
  return {root,worker,config:await worker.ready,hooks};
}

test('Live HTTP search synchronizes saved files and rejects unauthorized/invalid requests',
  {skip:!python,timeout:15000}, async t => {
    const {root,config} = await fixture(t);
    await writeFile(join(root,'main.py'),'def save():\n    return "first"\n');
    const first = await search('find save',{config,freshnessWaitMs:5000});
    assert.match(first.context, /first/);
    assert.equal(first.index.freshness,'verified-after-search');
    await writeFile(join(root,'main.py'),'def save():\n    return "second"\n');
    const next = await search('find save',{config,freshnessWaitMs:5000});
    assert.match(next.context,/second/);
    assert.notEqual(first.index.identity,next.index.identity);
    assert.equal((await indexStatus({config})).status,'ready');
    await assert.rejects(search('find save',{config:{...config,apiKey:'incorrect'}}),/401/);
    const invalid = await fetch(config.baseUrl+'/search',{method:'POST',headers:{authorization:`Bearer ${config.apiKey}`},
      body:JSON.stringify({query:'q',freshnessWaitMs:-1})});
    assert.equal(invalid.status,422);
    await writeFile(join(root,'main.py'),'def broken(\n');
    await assert.rejects(search('find save',{config,freshnessWaitMs:5000}),/Index unavailable/);
    await rm(join(root,'main.py'));
    const empty = await search('find save',{config,freshnessWaitMs:5000});
    assert.equal(empty.context,'');
  });

test('Live HTTP refuses results if source changes during model retrieval',
  {skip:!python,timeout:15000}, async t => {
    const {root,config,hooks} = await fixture(t);
    await writeFile(join(root,'main.py'),'def save():\n    return "before"\n');
    hooks.rerank = async () => {
      hooks.rerank = null;
      await writeFile(join(root,'main.py'),'def save():\n    return "after"\n');
    };
    await assert.rejects(search('find save',{config,freshnessWaitMs:5000}),/Source changed during search/);
    assert.match((await search('find save',{config,freshnessWaitMs:5000})).context,/after/);
  });

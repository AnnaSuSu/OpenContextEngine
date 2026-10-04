import { createServer } from 'node:http';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { startService } from '../../src/service.mjs';
import { venvPython } from '../../src/runtime.mjs';

export const python = process.env.OCE_PYTHON || ['.venv',
  '.pilot-state/language-adapters-venv','.pilot-state/baselines/cocoindex-venv']
  .map(path => venvPython(resolve(path))).find(existsSync);

// A deterministic protocol fixture, not a local model or retrieval quality test.
export async function fixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'opencontextengine 中文 '));
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
      } else if (request.url === '/v1/rerank') {
        if (hooks.rerank) await hooks.rerank(body);
        result = {results:body.documents.map((_,index) => ({index,relevance_score:.95})).reverse()};
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
  const settings = {python,config:{root,state:join(dir,'state'),port:0,
    serviceKey:'test-only-at-least-24-characters',embeddingUrl:modelUrl,
    embeddingIdentity:'https://test-model.invalid/v1',embeddingKey:'test-only',
    reranker:{baseUrl:modelUrl,model:'fixture',apiKey:'test-only'},pollSeconds:.05,debounceSeconds:0}};
  const worker = startService(settings, {log:() => {}});
  t.after(async () => {
    await worker.close();
    models.closeAllConnections();
    await new Promise(resolveClose => models.close(resolveClose));
    await rm(dir,{recursive:true,force:true});
  });
  return {root,worker,config:await worker.ready,hooks,settings,dir};
}

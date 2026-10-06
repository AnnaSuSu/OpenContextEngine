import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile, realpath, mkdir, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createMcpServer } from '../src/mcp.mjs';
import { createWorkspaceManager } from '../src/workspaces.mjs';
import { startService } from '../src/service.mjs';
import { fixture, python } from './helpers/live-service.mjs';
import { createServer } from 'node:http';

async function pendingClient(t, respond) {
  const requests = [];
  const http = createServer(async (request, response) => {
    let data = '';
    for await (const chunk of request) data += chunk;
    requests.push(JSON.parse(data));
    const [status, body] = respond(requests.length);
    response.writeHead(status,{'content-type':'application/json'}).end(JSON.stringify(body));
  });
  await new Promise(resolve => http.listen(0,'127.0.0.1',resolve));
  const server = createMcpServer({baseUrl:`http://127.0.0.1:${http.address().port}`,apiKey:'test-only'});
  const client = new Client({name:'pending-test',version:'1.0.0'});
  const [a,b] = InMemoryTransport.createLinkedPair();
  t.after(async () => {
    await client.close(); await server.close();
    http.closeAllConnections();
    await new Promise(resolve => http.close(resolve));
  });
  await server.connect(b); await client.connect(a);
  return {client,requests};
}

const pendingResponse = {code:'INDEX_UPDATING',error:'Index is updating',retryable:true,
  index:{mode:'live',status:'updating',progress:{stage:'embedding',completedDocuments:64,totalDocuments:100}}};

test('MCP retries pending synchronization once and returns recovered source', async t => {
  const {client,requests} = await pendingClient(t, attempt => attempt === 1 ? [503,pendingResponse]
    : [200,{context:'fresh source',retrievalMs:1,index:{mode:'live'}}]);
  const result = await client.callTool({name:'search_code',arguments:{query:'find source'}});
  assert.ok(!result.isError);
  assert.equal(result.structuredContent.context,'fresh source');
  assert.deepEqual(requests.map(r => r.freshnessWaitMs),[30000,10000]);
});

test('MCP exhausts one retry with a non-error updating status, never empty search results', async t => {
  const {client,requests} = await pendingClient(t, () => [503,pendingResponse]);
  const result = await client.callTool({name:'search_code',arguments:{query:'find source',freshnessWaitMs:50}});
  assert.equal(result.isError,false);
  assert.equal(result.structuredContent.status,'updating');
  assert.equal(result.structuredContent.retryable,true);
  assert.equal(result.structuredContent.context,undefined);
  assert.match(result.content[0].text,/64\/100/);
  assert.match(result.content[0].text,/search has not run yet/);
  assert.deepEqual(requests.map(r => r.freshnessWaitMs),[50,50]);
});

test('MCP zero wait returns pending immediately without retry', async t => {
  const {client,requests} = await pendingClient(t, () => [503,pendingResponse]);
  const result = await client.callTool({name:'search_code',arguments:{query:'find source',freshnessWaitMs:0}});
  assert.equal(result.isError,false);
  assert.equal(requests.length,1);
});

test('MCP preserves genuine index failures and never retries them', async t => {
  const {client,requests} = await pendingClient(t, () => [503,
    {code:'INDEX_UNAVAILABLE',error:'Index update failed: HTTPError',index:{status:'failed'}}]);
  const result = await client.callTool({name:'search_code',arguments:{query:'find source'}});
  assert.equal(result.isError,true);
  assert.match(result.content[0].text,/Index update failed: HTTPError/);
  assert.equal(requests.length,1);
});

test('MCP surfaces an indexing failure that occurs during the retry', async t => {
  const {client,requests} = await pendingClient(t, attempt => attempt === 1 ? [503,pendingResponse]
    : [503,{code:'INDEX_UNAVAILABLE',error:'Index update failed: HTTPError',index:{status:'failed'}}]);
  const result = await client.callTool({name:'search_code',arguments:{query:'find source'}});
  assert.equal(result.isError,true);
  assert.match(result.content[0].text,/Index update failed: HTTPError/);
  assert.equal(requests.length,2);
});

async function connect(t, config, legacy=false) {
  const transport = new StdioClientTransport({command:process.execPath,
    args:[resolve(legacy ? 'scripts/mcp-reponerve.mjs' : 'scripts/mcp-opencontextengine.mjs'),'--connect'],stderr:'pipe',
    env:{...process.env,...(legacy ? {REPONERVE_BASE_URL:config.baseUrl,REPONERVE_API_KEY:config.apiKey}
      : {OCE_BASE_URL:config.baseUrl,OCE_API_KEY:config.apiKey})}});
  const client = new Client({name:'opencontextengine-test',version:'1.0.0'});
  t.after(() => client.close());
  await client.connect(transport);
  return client;
}

test('Official MCP stdio client initializes, discovers tools and retrieves updated source',
  {skip:!python,timeout:15000}, async t => {
    const {root,config} = await fixture(t);
    await writeFile(join(root,'lib.py'),'def persist():\n    return "original"\n');
    const client = await connect(t,config);
    assert.equal(client.getServerVersion().name,'open-context-engine');
    const tools = (await client.listTools()).tools;
    assert.deepEqual(tools.map(tool => tool.name).sort(),['index_status','search_code']);
    assert.equal(tools[1].annotations.readOnlyHint,true);
    assert.equal(tools.find(tool => tool.name==='search_code').inputSchema.properties.budget.default,8000);
    let result = await client.callTool({name:'search_code',arguments:{query:'find persist',freshnessWaitMs:5000}});
    assert.ok(!result.isError);
    assert.match(result.content[0].text,/original/);
    const identity = result.structuredContent.index.identity;
    await writeFile(join(root,'lib.py'),'def persist():\n    return "updated"\n');
    result = await client.callTool({name:'search_code',arguments:{query:'find persist',freshnessWaitMs:5000}});
    assert.ok(!result.isError);
    assert.match(result.content[0].text,/updated/);
    assert.notEqual(result.structuredContent.index.identity,identity);
    const status = await client.callTool({name:'index_status',arguments:{}});
    assert.equal(status.structuredContent.root,await realpath(root));
    assert.equal(status.structuredContent.status,'ready');
    await writeFile(join(root,'lib.py'),'def unfinished(\n');
    const fallback = await client.callTool({name:'search_code',arguments:{query:'find unfinished',freshnessWaitMs:5000}});
    assert.ok(!fallback.isError);
    assert.match(fallback.content[0].text,/indexed as plain text/);
    assert.match(fallback.content[0].text,/def unfinished\(/);
    assert.doesNotMatch(fallback.content[0].text,/return "updated"/);
    assert.equal(fallback.structuredContent.index.degradedFiles,1);
    const degraded = (await client.callTool({name:'index_status',arguments:{}})).structuredContent;
    assert.equal(degraded.status,'ready');
    assert.equal(degraded.generation.parseDiagnostics[0].path,'lib.py');
    await writeFile(join(root,'lib.py'),'def persist():\n    return "repaired"\n');
    const repaired = await client.callTool({name:'search_code',arguments:{query:'find persist',freshnessWaitMs:5000}});
    assert.equal(repaired.structuredContent.index.degradedFiles,0);
    assert.match(repaired.content[0].text,/repaired/);
    assert.doesNotMatch(repaired.content[0].text,/indexed as plain text/);
    const compatible = await connect(t,config,true);
    assert.equal(compatible.getServerVersion().name,'open-context-engine');
    const compatibleStatus = await compatible.callTool({name:'index_status',arguments:{}});
    assert.ok(!compatibleStatus.isError);
    assert.equal(compatibleStatus.structuredContent.root,await realpath(root));
  });

test('MCP schema rejects invalid inputs and reports service authentication failure',
  {skip:!python,timeout:15000}, async t => {
    const {config} = await fixture(t);
    const client = await connect(t,{...config,apiKey:'wrong'});
    const invalid = await client.callTool({name:'search_code',arguments:{query:'',budget:10}});
    assert.equal(invalid.isError,true);
    const unauthorized = await client.callTool({name:'index_status',arguments:{}});
    assert.equal(unauthorized.isError,true);
    assert.match(unauthorized.content[0].text,/401/);
    const wrongProject = await client.callTool({name:'index_status',arguments:{directory_path:'/other/project'}});
    assert.equal(wrongProject.isError,true);
    assert.match(wrongProject.content[0].text,/Connected-service mode/);
  });

test('Automatic MCP launcher discovers tools without choosing a startup directory', {timeout:5000}, async t => {
  const transport = new StdioClientTransport({command:process.execPath,
    args:[resolve('scripts/mcp-opencontextengine.mjs')],stderr:'pipe'});
  const client = new Client({name:'auto-workspace-test',version:'1.0.0'});
  t.after(() => client.close());
  await client.connect(transport);
  assert.match(client.getInstructions(),/directory_path/);
  const tools = (await client.listTools()).tools;
  for (const tool of tools) assert.ok(tool.inputSchema.required.includes('directory_path'));
  const missing = await client.callTool({name:'index_status',arguments:{}});
  assert.equal(missing.isError,true);
  const relative = await client.callTool({name:'index_status',arguments:{directory_path:'relative'}});
  assert.equal(relative.isError,true);
  assert.match(relative.content[0].text,/absolute project directory/);
});

test('Automatic MCP routes concurrent projects, reuses workers and keeps saved changes isolated',
  {skip:!python,timeout:20000}, async t => {
    const {dir,settings} = await fixture(t);
    const first = join(dir,'alpha'), second = join(dir,'beta');
    await mkdir(first); await mkdir(second);
    await writeFile(join(first,'lib.py'),'def persist():\n    return "alpha_only"\n');
    await writeFile(join(second,'lib.py'),'def persist():\n    return "beta_only"\n');
    const workers = [];
    const workspaces = createWorkspaceManager({state:join(dir,'multi-state')},{
      configure: ({root,state}) => ({...settings,config:{...settings.config,root,state}}),
      start: config => {const worker = startService(config,{log:()=>{}}); workers.push(worker); return worker;},
    });
    const server = createMcpServer(undefined,{resolveConfig:workspaces.get,automatic:true});
    const client = new Client({name:'multi-workspace-test',version:'1.0.0'});
    const [clientTransport,serverTransport] = InMemoryTransport.createLinkedPair();
    try {
      await server.connect(serverTransport);
      await client.connect(clientTransport);
      const query = path => client.callTool({name:'search_code',arguments:{directory_path:path,query:'find persist',freshnessWaitMs:5000}});
      const [a,b,aAgain] = await Promise.all([query(first),query(second),query(first)]);
      for (const result of [a,b,aAgain]) assert.ok(!result.isError,JSON.stringify(result));
      assert.match(a.content[0].text,/alpha_only/);
      assert.doesNotMatch(a.content[0].text,/beta_only/);
      assert.match(b.content[0].text,/beta_only/);
      assert.doesNotMatch(b.content[0].text,/alpha_only/);
      assert.equal(a.structuredContent.index.identity,aAgain.structuredContent.index.identity);
      assert.equal(workers.length,2);
      const status = await client.callTool({name:'index_status',arguments:{directory_path:first}});
      assert.equal(status.structuredContent.root,await realpath(first));
      await writeFile(join(first,'lib.py'),'def persist():\n    return "alpha_updated"\n');
      const changed = await query(first);
      assert.ok(!changed.isError);
      assert.match(changed.content[0].text,/alpha_updated/);
      const untouched = await query(second);
      assert.equal(untouched.structuredContent.index.identity,b.structuredContent.index.identity);
      const badPath = await query(join(dir,'missing'));
      assert.equal(badPath.isError,true);
      assert.equal(workers.length,2);
      await rm(join(first,'lib.py'));
      const deleted = await query(first);
      assert.ok(!deleted.isError);
      assert.doesNotMatch(deleted.content[0].text,/alpha_updated/);
      await workers[1].close();
      const restarted = await query(second);
      assert.ok(!restarted.isError,JSON.stringify(restarted));
      assert.match(restarted.content[0].text,/beta_only/);
      assert.equal(restarted.structuredContent.index.identity,b.structuredContent.index.identity);
      assert.equal(workers.length,3);
    } finally {
      await client.close();
      await server.close();
      await workspaces.close();
    }
    assert.ok(workers.every(worker => worker.child.exitCode !== null || worker.child.signalCode !== null));
  });

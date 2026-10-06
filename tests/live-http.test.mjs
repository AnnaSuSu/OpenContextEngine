import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile, rm } from 'node:fs/promises';
import { join, delimiter, dirname, resolve } from 'node:path';
import { search, indexStatus } from '../src/client.mjs';
import { fixture, python } from './helpers/live-service.mjs';
import { startService } from '../src/service.mjs';

test('A missing worker executable fails startup and closes without hanging', {timeout:2000}, async () => {
  const worker = startService({python:'/nonexistent/opencontextengine/python',config:{}},{log:()=>{}});
  await assert.rejects(worker.ready,/ENOENT/);
  await worker.close();
});

test('Live HTTP search synchronizes saved files and rejects unauthorized/invalid requests',
  {skip:!python,timeout:15000}, async t => {
    const {root,config} = await fixture(t);
    await writeFile(join(root,'main.py'),'def save():\n    return "first"\n');
    const first = await search('find save',{config,freshnessWaitMs:5000});
    assert.match(first.context, /first/);
    assert.equal(first.index.freshness,'verified-after-search');
    await writeFile(join(root,'main.py'),'def save():\n    return "second 中文"\n');
    const next = await search('find save',{config,freshnessWaitMs:5000});
    assert.match(next.context,/second/);
    assert.match(next.context,/中文/);
    assert.notEqual(first.index.identity,next.index.identity);
    assert.equal((await indexStatus({config})).status,'ready');
    await assert.rejects(search('find save',{config:{...config,apiKey:'incorrect'}}),/401/);
    const invalid = await fetch(config.baseUrl+'/search',{method:'POST',headers:{authorization:`Bearer ${config.apiKey}`},
      body:JSON.stringify({query:'q',freshnessWaitMs:-1})});
    assert.equal(invalid.status,422);
    await writeFile(join(root,'main.py'),'def broken(\n');
    const fallback = await search('find broken',{config,freshnessWaitMs:5000});
    assert.match(fallback.context,/def broken\(/);
    assert.doesNotMatch(fallback.context,/second/);
    assert.equal(fallback.index.degradedFiles,1);
    await rm(join(root,'main.py'));
    const empty = await search('find save',{config,freshnessWaitMs:5000});
    assert.equal(empty.context,'');
    assert.equal(empty.index.degradedFiles,0);
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

test('Pending HTTP search reports typed progress and recovers after embedding completes',
  {skip:!python,timeout:15000}, async t => {
    const {root,config,hooks} = await fixture(t);
    let entered, release;
    const started = new Promise(resolve => {entered = resolve;});
    const blocked = new Promise(resolve => {release = resolve;});
    hooks.embedding = async () => {entered(); await blocked;};
    try {
      await writeFile(join(root,'pending.txt'),'indexing progress evidence\n');
      await started;
      await assert.rejects(search('find evidence',{config,freshnessWaitMs:0}), error => {
        assert.equal(error.code,'INDEX_UPDATING');
        assert.equal(error.index.status,'updating');
        assert.deepEqual(error.index.progress,{stage:'embedding',completedDocuments:0,totalDocuments:1});
        return true;
      });
    } finally {hooks.embedding = null; release();}
    const result = await search('find evidence',{config,freshnessWaitMs:5000});
    assert.match(result.context,/indexing progress evidence/);
    assert.equal((await indexStatus({config})).progress,null);
  });

test('Managed workers can parse JavaScript when the desktop client PATH does not contain Node',
  {skip:!python,timeout:15000}, async t => {
    const original = process.env.PATH;
    let service;
    try {
      process.env.PATH = original.split(delimiter)
        .filter(directory => resolve(directory).toLowerCase() !== dirname(process.execPath).toLowerCase()).join(delimiter);
      service = await fixture(t);
    } finally {process.env.PATH = original;}
    await writeFile(join(service.root,'store.js'),'export function persist() { return "desktop-path-ready"; }\n');
    const result = await search('find persist',{config:service.config,freshnessWaitMs:5000});
    assert.match(result.context,/desktop-path-ready/);
  });

test('A concurrent search can queue longer than five seconds behind model retrieval',
  {skip:!python, timeout:20000}, async t => {
    const {root,config,hooks} = await fixture(t);
    await writeFile(join(root, 'main.py'), 'def persist():\n    return "queued_result"\n');
    let entered;
    const started = new Promise(resolve => {entered = resolve;});
    hooks.rerank = async () => {
      hooks.rerank = null;
      entered();
      await new Promise(resolve => setTimeout(resolve, 5500));
    };
    const first = search('find persist', {config, freshnessWaitMs:5000});
    await started;
    const second = search('find persist', {config, freshnessWaitMs:5000});
    const [a, b] = await Promise.all([first, second]);
    assert.match(a.context, /queued_result/);
    assert.match(b.context, /queued_result/);
    assert.ok(b.queueMs >= 5000, b.queueMs);
  });

test('Default HTTP, client and MCP budgets return 8k evidence while explicit 4k remains supported',
  {skip:!python,timeout:20000}, async t => {
    const {root,config} = await fixture(t);
    const source = Array.from({length:32},(_,i) => `def persist_${i}():\n`
      + Array.from({length:35},(_,j) => `    value_${j} = "record_${i}_${j}"\n`).join('')
      + '    return value_34\n').join('\n');
    await writeFile(join(root,'records.py'),source);
    const defaultClient = await search('Find record persistence implementations',{config,freshnessWaitMs:5000});
    const explicit8k = await search('Find record persistence implementations',{config,budget:8000,freshnessWaitMs:5000});
    const explicit4k = await search('Find record persistence implementations',{config,budget:4000,freshnessWaitMs:5000});
    assert.equal(defaultClient.context,explicit8k.context);
    assert.ok(defaultClient.tokens>4000 && defaultClient.tokens<=8000,defaultClient.tokens);
    assert.ok(explicit4k.tokens<=4000,explicit4k.tokens);
    const raw = await fetch(config.baseUrl+'/search',{method:'POST',
      headers:{authorization:`Bearer ${config.apiKey}`,'content-type':'application/json'},
      body:JSON.stringify({query:'Find record persistence implementations',freshnessWaitMs:5000})});
    assert.equal(raw.status,200);
    assert.equal((await raw.json()).context,explicit8k.context);
    const {Client} = await import('@modelcontextprotocol/sdk/client/index.js');
    const {InMemoryTransport} = await import('@modelcontextprotocol/sdk/inMemory.js');
    const {createMcpServer} = await import('../src/mcp.mjs');
    const server=createMcpServer(config);
    const client=new Client({name:'default-budget-test',version:'1.0.0'});
    const [a,b]=InMemoryTransport.createLinkedPair();
    try {
      await server.connect(b);await client.connect(a);
      const result=await client.callTool({name:'search_code',arguments:{query:'Find record persistence implementations',freshnessWaitMs:5000}});
      assert.ok(!result.isError,JSON.stringify(result));
      assert.equal(result.structuredContent.context,explicit8k.context);
      const smaller=await client.callTool({name:'search_code',arguments:{query:'Find record persistence implementations',budget:4000,freshnessWaitMs:5000}});
      assert.ok(!smaller.isError,JSON.stringify(smaller));
      assert.equal(smaller.structuredContent.context,explicit4k.context);
    } finally {await client.close();await server.close();}
  });

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

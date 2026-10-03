import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile, realpath } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { fixture, python } from './helpers/live-service.mjs';

async function connect(t, config) {
  const transport = new StdioClientTransport({command:process.execPath,
    args:[resolve('scripts/mcp-reponerve.mjs'),'--connect'],stderr:'pipe',
    env:{...process.env,REPONERVE_BASE_URL:config.baseUrl,REPONERVE_API_KEY:config.apiKey}});
  const client = new Client({name:'reponerve-test',version:'1.0.0'});
  t.after(() => client.close());
  await client.connect(transport);
  return client;
}

test('Official MCP stdio client initializes, discovers tools and retrieves updated source',
  {skip:!python,timeout:15000}, async t => {
    const {root,config} = await fixture(t);
    await writeFile(join(root,'lib.py'),'def persist():\n    return "original"\n');
    const client = await connect(t,config);
    const tools = (await client.listTools()).tools;
    assert.deepEqual(tools.map(tool => tool.name).sort(),['index_status','search_code']);
    assert.equal(tools[1].annotations.readOnlyHint,true);
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
    const failure = await client.callTool({name:'search_code',arguments:{query:'find persist',freshnessWaitMs:5000}});
    assert.equal(failure.isError,true);
    assert.match(failure.content[0].text,/Index unavailable/);
    assert.doesNotMatch(failure.content[0].text,/return "updated"/);
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
  });

// Opt-in end-to-end smoke: calls the configured remote models, never loads weights.
import assert from 'node:assert/strict';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { resolve, join } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const run = resolve('.pilot-state/mcp-smoke', new Date().toISOString().replaceAll(':','-'));
const root = join(run,'repo'), state = join(run,'index');
await mkdir(root,{recursive:true});
execFileSync('git',['init','-q',root]);
await writeFile(join(root,'version.py'),'def current_version():\n    return "live-version-one"\n');
await writeFile(join(root,'helper.js'),'export function double(value) { return value * 2; }\n');
await writeFile(join(root,'config.yaml'),'mode: development\n');
const transport = new StdioClientTransport({command:process.execPath,
  args:[resolve('scripts/mcp-opencontextengine.mjs'),'--root',root,'--state',state],
  env:{...process.env},stderr:'pipe'});
const client = new Client({name:'opencontextengine-remote-smoke',version:'1.0.0'});
const report = {startedAt:new Date().toISOString(),checks:[],modelCalls:'configured remote endpoints'};
try {
  await client.connect(transport);
  transport.stderr?.resume();
  assert.deepEqual((await client.listTools()).tools.map(t=>t.name).sort(),['index_status','search_code']);
  const query = 'Find the Python current_version function and its current return value.';
  const search = async () => {
    const result = await client.callTool({name:'search_code',arguments:{query,freshnessWaitMs:120000}},undefined,{timeout:160000});
    if (result.isError) throw new Error(result.content[0].text);
    return result.structuredContent;
  };
  const first = await search();
  assert.match(first.context,/live-version-one/);
  report.checks.push({name:'initial-index-and-search',index:first.index,elapsedMs:first.clientElapsedMs});
  await writeFile(join(root,'version.py'),'\n\ndef current_version():\n    return "live-version-two"\n');
  const next = await search();
  assert.match(next.context,/live-version-two/);
  assert.doesNotMatch(next.context,/live-version-one/);
  assert.notEqual(next.index.identity,first.index.identity);
  const status = (await client.callTool({name:'index_status',arguments:{}})).structuredContent;
  assert.ok(status.generation.reusedUnits >= 2);
  assert.equal(status.generation.embeddedDocuments,1);
  report.checks.push({name:'saved-edit-incremental-search',index:next.index,elapsedMs:next.clientElapsedMs,
    embeddedDocuments:status.generation.embeddedDocuments,reusedUnits:status.generation.reusedUnits});
  await rm(join(root,'helper.js'));
  const removed = await search();
  assert.doesNotMatch(removed.context,/helper\.js/);
  report.checks.push({name:'deleted-file-removed',index:removed.index,elapsedMs:removed.clientElapsedMs});
  // EOF closes the managed worker. Reopening the same index proves writer release.
  await client.close();
  const restart = new Client({name:'opencontextengine-restart-smoke',version:'1.0.0'});
  try {
    await restart.connect(new StdioClientTransport({command:process.execPath,
      args:[resolve('scripts/mcp-opencontextengine.mjs'),'--root',root,'--state',state],env:{...process.env},stderr:'pipe'}));
    const result = await restart.callTool({name:'search_code',arguments:{query,freshnessWaitMs:120000}},undefined,{timeout:160000});
    assert.ok(!result.isError, result.content?.[0]?.text);
    assert.equal(result.structuredContent.index.identity,removed.index.identity);
    report.checks.push({name:'restart-restores-generation',identity:removed.index.identity});
  } finally {await restart.close();}
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  report.error = error.message;
  process.exitCode = 1;
} finally {
  await client.close();
  report.finishedAt = new Date().toISOString();
  await writeFile(join(run,'report.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({report:join(run,'report.json'),...report},null,2));
}

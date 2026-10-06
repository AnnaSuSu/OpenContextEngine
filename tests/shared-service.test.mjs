import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFile, writeFile, mkdir, symlink, stat, readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { fixture, python } from './helpers/live-service.mjs';
import { startSharedService } from '../src/shared-service.mjs';
import { search } from '../src/client.mjs';

const cleanups = new WeakMap();
async function sharedFixture(t) {
  const callbacks = [];
  cleanups.set(t, callbacks);
  return fixture(t, {beforeCleanup:async ({dir}) => {
    await Promise.all(callbacks.map(close => close()));
    // Close clients first so their heartbeats cannot restart a test worker during cleanup.
    const files = await readdir(dir, {recursive:true});
    const pids = [];
    for (const file of files.filter(file => /(^|[/\\])worker\.json$/.test(file))) {
      try {
        const {pid} = JSON.parse(await readFile(join(dir, file), 'utf8'));
        process.kill(pid, 'SIGKILL');
        pids.push(pid);
      } catch (error) {if (!['ENOENT', 'ESRCH'].includes(error.code)) throw error;}
    }
    await eventually(() => pids.every(pid => {
      try {process.kill(pid, 0); return false;} catch (error) {return error.code === 'ESRCH';}
    }));
  }});
}

async function eventually(check, timeout = 8000) {
  const deadline = Date.now() + timeout;
  do {if (await check()) return; await delay(50);} while (Date.now() < deadline);
  assert.fail('Condition did not become true before timeout');
}
async function record(state) {return JSON.parse(await readFile(join(state, 'worker.json'), 'utf8'));}
async function absent(state) {
  try {await record(state); return false;} catch (error) {if (error.code === 'ENOENT') return true; throw error;}
}
function shared(t, settings, options = {}) {
  const handle = startSharedService(settings, {idleSeconds:.3, leaseSeconds:1, ...options});
  cleanups.get(t).push(() => handle.close());
  return handle;
}

test('Shared workers arbitrate concurrent starts, validate compatibility, survive detach and recover from crashes',
  {skip:!python, timeout:30000}, async t => {
    const {dir, root, settings} = await sharedFixture(t);
    const state = join(dir, 'shared');
    settings.config = {...settings.config, state};
    await writeFile(join(root, 'lib.py'), 'def persist():\n    return "shared_result"\n');
    const first = shared(t, settings), second = shared(t, settings);
    const [a, b] = await Promise.all([first.ready, second.ready]);
    assert.deepEqual(a, b);
    const original = await record(state);
    if (process.platform !== 'win32') assert.equal((await stat(join(state, 'worker.json'))).mode & 0o777, 0o600);
    assert.match((await search('find persist', {config:a, freshnessWaitMs:5000})).context, /shared_result/);
    for (const difference of [{embeddingKey:'different-credential'}, {languageOptions:{go:{mode:'types'}}}, {root:dir}]) {
      const wrong = shared(t, {...settings, config:{...settings.config, ...difference}});
      await assert.rejects(wrong.ready, /incompatible configuration/);
    }
    const unauthorized = await fetch(a.baseUrl + '/lease', {method:'POST', body:'{}'});
    assert.equal(unauthorized.status, 401);
    assert.equal((await record(state)).instanceId, original.instanceId);
    await first.close();
    await delay(1400); // More than both the lease TTL and idle grace; the second client's heartbeat keeps it alive.
    assert.deepEqual(await second.get(), b);
    process.kill(original.pid, 'SIGKILL');
    const recovered = await second.get();
    assert.notEqual((await record(state)).instanceId, original.instanceId);
    assert.match((await search('find persist', {config:recovered, freshnessWaitMs:5000})).context, /shared_result/);
    await second.close();
    await eventually(() => absent(state));
  });

test('Dead discovery records are replaced only after acquiring the writer lock; path aliases share a worker',
  {skip:!python, timeout:20000}, async t => {
    const {dir, root, settings} = await sharedFixture(t);
    const state = join(dir, 'shared'), alias = join(dir, 'alias');
    await mkdir(state);
    await symlink(root, alias, process.platform === 'win32' ? 'junction' : 'dir');
    await writeFile(join(state, 'worker.json'), JSON.stringify({protocol:1, port:1, instanceId:'dead', apiKey:'a'.repeat(64)}));
    const a = shared(t, {...settings, config:{...settings.config, state}});
    const b = shared(t, {...settings, config:{...settings.config, root:alias, state}});
    assert.deepEqual(await a.ready, await b.ready);
    await a.close(); await b.close();
    await eventually(() => absent(state));
  });

test('A shared writer survives its launcher closing the startup pipe before readiness',
  {skip:!python, timeout:10000}, async t => {
    const {dir, settings} = await sharedFixture(t);
    const state = join(dir, 'orphan-start');
    const child = spawn(python, [resolve('scripts/retrieval-server.py')], {
      detached:true, windowsHide:true, stdio:['pipe', 'pipe', 'ignore'],
      env:{...process.env, PYTHONUTF8:'1', PYTHONIOENCODING:'utf-8'},
    });
    await once(child, 'spawn');
    child.stdout.destroy();
    child.stdin.end(JSON.stringify({...settings.config, state, serviceKey:'a'.repeat(64),
      shared:{fingerprint:'test', leaseSeconds:1, idleSeconds:2}}) + '\n');
    child.unref();
    cleanups.get(t).push(async () => {
      if (child.exitCode === null && child.signalCode === null) {
        const exited = once(child, 'exit');
        child.kill('SIGKILL');
        await exited;
      }
    });
    await eventually(async () => !await absent(state));
    const info = await record(state);
    const response = await fetch(`http://127.0.0.1:${info.port}/lease`, {
      method:'POST', headers:{authorization:`Bearer ${info.apiKey}`},
      body:JSON.stringify({instanceId:info.instanceId, fingerprint:'test', leaseId:'survivor'}),
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).pid, child.pid);
  });

test('An older private worker retains its lock and gets an actionable error instead of being killed',
  {skip:!python, timeout:10000}, async t => {
    const {settings, worker} = await sharedFixture(t);
    const handle = shared(t, settings, {startupMs:1500});
    await assert.rejects(handle.ready, /running writer.*older or manually started worker/);
    assert.equal(worker.child.exitCode, null);
    assert.equal(worker.child.signalCode, null);
  });

async function mcp(t, dir, state, modelUrl, overrides = {}) {
  // Use the actual automatic-mode launcher in independent OS processes. The local HTTP
  // endpoint is a deterministic protocol fixture, reached through the supported tunnel settings.
  const env = {...process.env, OCE_CONFIG_HOME:join(dir, 'config'), OCE_PYTHON:python,
    EMBEDDING_BASE_URL:'https://fixture.invalid/v1', EMBEDDING_API_KEY:'test-only', EMBEDDING_MODEL:'fixture',
    EMBEDDING_SSH_TUNNEL_URL:modelUrl, EMBEDDING_SSH_REMOTE:'test@fixture.invalid:22',
    RERANK_BASE_URL:'https://fixture.invalid/v1', RERANK_API_KEY:'test-only', RERANK_MODEL:'fixture',
    RERANK_SSH_TUNNEL_URL:modelUrl, RERANK_SSH_REMOTE:'test@fixture.invalid:22',
    RERANK_REMOTE_RUNTIME_URL:'', OCE_RERANK_API:'rerank', OCE_EMBEDDING_DIMENSIONS:'1024',
    OCE_EMBEDDING_BATCH_SIZE:'64', OCE_EMBEDDING_REVISION:'1', OCE_POLL_SECONDS:'0.05',
    OCE_DEBOUNCE_SECONDS:'0', OCE_LANGUAGE_OPTIONS:'{}', ...overrides};
  const transport = new StdioClientTransport({command:process.execPath,
    args:[resolve('scripts/mcp-opencontextengine.mjs'), '--state', state], stderr:'pipe', env});
  const client = new Client({name:'shared-process-test', version:'1.0.0'});
  cleanups.get(t).push(() => client.close());
  await client.connect(transport);
  return {client, transport};
}

test('Independent automatic MCP processes share one writer across projects and survive the launching process exiting',
  {skip:!python, timeout:30000}, async t => {
    const {dir, root, settings} = await sharedFixture(t);
    const state = join(dir, 'mcp-states'), other = join(dir, 'other');
    await mkdir(other);
    await writeFile(join(root, 'lib.py'), 'def persist():\n    return "first_project"\n');
    await writeFile(join(other, 'lib.py'), 'def persist():\n    return "second_project"\n');
    const {createHash} = await import('node:crypto');
    const {realpath} = await import('node:fs/promises');
    const paths = await Promise.all([root, other].map(async path => join(state,
      createHash('sha256').update(await realpath(path)).digest('hex').slice(0,24))));
    const [a, b] = await Promise.all([mcp(t, dir, state, settings.config.embeddingUrl), mcp(t, dir, state, settings.config.embeddingUrl)]);
    const query = (client, path) => client.callTool({name:'search_code', arguments:{directory_path:path, query:'find persist', freshnessWaitMs:5000}});
    const [one, two, different] = await Promise.all([query(a.client, root), query(b.client, root), query(b.client, other)]);
    for (const result of [one,two,different]) assert.ok(!result.isError, JSON.stringify(result));
    assert.match(one.content[0].text, /first_project/);
    assert.match(two.content[0].text, /first_project/);
    assert.match(different.content[0].text, /second_project/);
    assert.doesNotMatch(different.content[0].text, /first_project/);
    const before = await record(paths[0]), otherRecord = await record(paths[1]);
    assert.notEqual(before.pid, otherRecord.pid);
    // Kill both original MCPs separately, attaching a survivor before each exit. This
    // necessarily covers the original launcher's abrupt exit, regardless of who won the race.
    const c = await mcp(t, dir, state, settings.config.embeddingUrl);
    assert.ok(!(await query(c.client, root)).isError);
    process.kill(a.transport.pid, 'SIGKILL');
    await b.client.close();
    await writeFile(join(root, 'lib.py'), 'def persist():\n    return "after_client_exit"\n');
    const after = await query(c.client, root);
    assert.ok(!after.isError, JSON.stringify(after));
    assert.match(after.content[0].text, /after_client_exit/);
    assert.equal((await record(paths[0])).instanceId, before.instanceId);
    process.kill(before.pid, 'SIGKILL');
    const recovered = await query(c.client, root);
    assert.ok(!recovered.isError, JSON.stringify(recovered));
    assert.match(recovered.content[0].text, /after_client_exit/);
    assert.notEqual((await record(paths[0])).instanceId, before.instanceId);
  });

import { createHash, createHmac, randomBytes, randomUUID } from 'node:crypto';
import { readFile, mkdir, realpath } from 'node:fs/promises';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { projectRoot } from './config.mjs';
import { startService } from './service.mjs';

const protocol = 1;
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort()
    .filter(key => value[key] !== undefined).map(key => [key, stable(value[key])]));
  return value;
}
function runtimeIdentity() {
  const hash = createHash('sha256');
  function add(path) {
    for (const entry of readdirSync(join(projectRoot, path), {withFileTypes:true}).sort((a,b) => a.name.localeCompare(b.name))) {
      const name = `${path}/${entry.name}`;
      if (entry.isDirectory() && entry.name !== '__pycache__') add(name);
      else if (entry.isFile() && /\.(py|mjs|go)$/.test(name)) hash.update(name).update(readFileSync(join(projectRoot, name)));
    }
  }
  add('src/retrieval');
  for (const name of ['scripts/retrieval-server.py', 'requirements.txt']) hash.update(readFileSync(join(projectRoot, name)));
  hash.update(JSON.parse(readFileSync(join(projectRoot, 'package.json'))).version);
  return hash.digest('hex');
}

// A handle owns a renewable lease, never the lifetime of the shared child process.
export function startSharedService(settings, {startupMs = 15000, leaseSeconds = 15, idleSeconds = 30, start = startService} = {}) {
  const runtime = runtimeIdentity();
  let configured, connection, pending, timer, closed = false, closePromise;
  const leaseId = randomUUID();
  const initialized = (async () => {
    await mkdir(settings.config.state, {recursive:true, mode:0o700});
    const root = await realpath(settings.config.root), state = await realpath(settings.config.state);
    const config = {...settings.config, root, state};
    const {serviceKey, port, shared, ...behavior} = config;
    const identity = JSON.stringify(stable({protocol, runtime, config:behavior,
      python:settings.python, workerEnv:settings.workerEnv || {}}));
    configured = {config, identity, record:join(state, 'worker.json')};
  })();

  function fingerprint(key) {
    // Credentials participate in compatibility without a reusable plaintext/hash in discovery files.
    return createHmac('sha256', key).update(configured.identity).digest('hex');
  }
  async function readRecord() {
    let record;
    try {record = JSON.parse(await readFile(configured.record, 'utf8'));}
    catch (error) {
      if (error.code === 'ENOENT' || error instanceof SyntaxError) return;
      throw error;
    }
    if (!record || !Number.isInteger(record.port) || record.port < 1 || record.port > 65535 ||
        typeof record.apiKey !== 'string' || !/^[a-f0-9]{64}$/.test(record.apiKey) ||
        typeof record.instanceId !== 'string') return;
    // Discovery cannot redirect credentials or requests off this machine.
    return {...record, baseUrl:`http://127.0.0.1:${record.port}`};
  }
  async function lease(record, release = false) {
    const response = await fetch(record.baseUrl + (release ? '/release' : '/lease'), {
      method:'POST', redirect:'error', signal:AbortSignal.timeout(1500),
      headers:{'content-type':'application/json', authorization:`Bearer ${record.apiKey}`},
      body:JSON.stringify({instanceId:record.instanceId, fingerprint:fingerprint(record.apiKey), leaseId}),
    });
    const body = await response.json();
    if (response.status === 409 && body.code === 'CONFIG_MISMATCH') {
      throw Object.assign(new Error(body.error), {code:'CONFIG_MISMATCH'});
    }
    if (!response.ok || body.instanceId !== record.instanceId || record.protocol !== protocol ||
        !Number.isFinite(body.leaseSeconds) || body.leaseSeconds <= 0) throw new Error('Shared worker handshake failed');
    return {...record, leaseSeconds:body.leaseSeconds};
  }
  function schedule(record) {
    clearTimeout(timer);
    timer = setTimeout(() => {void get().catch(() => {});}, record.leaseSeconds * 1000 / 3);
    timer.unref();
  }
  async function connect() {
    await initialized;
    const deadline = performance.now() + startupMs;
    let nextSpawn = 0, lastBusy;
    while (!closed && performance.now() < deadline) {
      const record = connection || await readRecord();
      if (record) {
        try {
          connection = await lease(record);
          if (closed) {await lease(connection, true).catch(() => {}); break;}
          schedule(connection);
          return {baseUrl:connection.baseUrl, apiKey:connection.apiKey};
        } catch (error) {
          connection = undefined;
          if (error.code === 'CONFIG_MISMATCH') throw error;
        }
      }
      if (performance.now() >= nextSpawn) {
        if (runtimeIdentity() !== runtime) throw new Error('Worker runtime changed on disk; restart this MCP client');
        const key = randomBytes(32).toString('hex');
        const worker = start({...settings, config:{...configured.config, port:0, serviceKey:key,
          shared:{fingerprint:fingerprint(key), leaseSeconds, idleSeconds}}}, {log:() => {}, startupMs:Math.max(1, deadline - performance.now())});
        try {await worker.ready;}
        catch (error) {
          await worker.close();
          // A retry near the overall deadline may have too little time to import
          // Python. Preserve the writer conflict already established by an earlier attempt.
          if (error.code === 'STARTUP_TIMEOUT' && lastBusy) break;
          if (error.code !== 'INDEX_LOCKED') throw error;
          lastBusy = error;
        }
        nextSpawn = performance.now() + 1000;
      }
      await delay(100);
    }
    if (closed) throw new Error('MCP workspace manager is shutting down');
    throw new Error(lastBusy
      ? `${lastBusy.message}. No compatible shared worker became available. An older or manually started worker may own this index; close its clients or connect to it explicitly.`
      : 'Shared retrieval worker startup or connection timed out');
  }
  function get() {
    if (closed) return Promise.reject(new Error('MCP workspace manager is shutting down'));
    if (!pending) {
      pending = connect().finally(() => {pending = undefined;});
    }
    return pending;
  }
  function close() {
    if (!closePromise) {
      closed = true;
      clearTimeout(timer);
      closePromise = (async () => {
        await pending?.catch(() => {});
        if (connection) await lease(connection, true).catch(() => {});
        connection = undefined;
      })();
    }
    return closePromise;
  }
  return {ready:get(), get, close};
}

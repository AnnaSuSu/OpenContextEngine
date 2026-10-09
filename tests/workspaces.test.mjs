import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtemp, mkdir, writeFile, symlink, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createWorkspaceManager } from '../src/workspaces.mjs';

async function setup(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'oce-workspaces-'));
  const first = join(dir, 'first'), second = join(dir, 'second');
  await mkdir(first); await mkdir(second);
  const started = [];
  const manager = createWorkspaceManager(options.fixed ? {root:first,state:join(dir,'fixed-state')}
    : {state:join(dir,'states')}, {
    idleMs:options.idleMs ?? 120000, maxWorkspaces:options.maxWorkspaces ?? 3,
    configure: value => value,
    start: settings => {
      const child = new EventEmitter();
      const worker = {child, settings, closes:0, ready:options.ready?.(started.length) ?? Promise.resolve({root:settings.root}),
        async close() {this.closes++; child.emit('exit', 0);}};
      started.push(worker);
      return worker;
    },
  });
  t.after(async () => {await manager.close(); await rm(dir, {recursive:true,force:true});});
  return {manager, started, dir, first, second};
}

test('Workspace routing canonicalizes aliases, deduplicates concurrent starts and separates state', async t => {
  let ready;
  const gate = new Promise(resolve => {ready = resolve;});
  const {manager, started, dir, first, second} = await setup(t, {ready: () => gate});
  const alias = join(dir,'alias');
  await symlink(first,alias,process.platform === 'win32' ? 'junction' : 'dir');
  const a = manager.get(first), b = manager.get(alias), c = manager.get(second);
  assert.equal(started.length,2);
  assert.notEqual(started[0].settings.state,started[1].settings.state);
  assert.equal(started[0].settings.root,await realpath(first));
  ready({baseUrl:'fixture'});
  assert.equal(await a,await b);
  await c;
  await manager.get(first);
  assert.equal(started.length,2);
  await manager.close();
  assert.deepEqual(started.map(worker => worker.closes),[1,1]);
  await assert.rejects(manager.get(first),/shutting down/);
});

test('Workspace routing rejects missing, relative and non-directory paths before starting a worker', async t => {
  const {manager,started,dir} = await setup(t);
  await writeFile(join(dir,'file'),'source');
  for (const path of [undefined, '', 'relative', join(dir,'missing'), join(dir,'file')]) {
    await assert.rejects(manager.get(path));
  }
  assert.equal(started.length,0);
});

test('Fixed workspace mode accepts its own path and refuses switching projects', async t => {
  const {manager,started,first,second,dir} = await setup(t,{fixed:true});
  await manager.get();
  await manager.get(first);
  await assert.rejects(manager.get(second),/fixed to --root/);
  assert.equal(started.length,1);
  assert.equal(started[0].settings.state,join(dir,'fixed-state'));
});

test('Failed startup is cleaned up and a later call can retry', async t => {
  const {manager,started,first} = await setup(t,{ready: n => n === 0 ? Promise.reject(new Error('startup failed')) : undefined});
  await assert.rejects(manager.get(first),/startup failed/);
  assert.equal(started[0].closes,1);
  await manager.get(first);
  assert.equal(started.length,2);
});

test('Exited workers are restarted and closing also stops a pending startup', async t => {
  let ready;
  const {manager,started,first} = await setup(t,{ready: n => n === 1 ? new Promise(resolve => {ready=resolve;}) : undefined});
  await manager.get(first);
  started[0].child.emit('exit',1);
  const pending = manager.get(first);
  assert.equal(started.length,2);
  await manager.close();
  assert.equal(started[1].closes,1);
  ready({baseUrl:'fixture'});
  await pending;
});


test('Unused workspace handles release leases and capacity evicts the least recent project', async t => {
  const {manager,started,first,second} = await setup(t,{idleMs:40,maxWorkspaces:1});
  await manager.get(first);
  await manager.get(second);
  assert.equal(started[0].closes,1);
  await new Promise(resolve=>setTimeout(resolve,120));
  assert.equal(started[1].closes,1);
  await manager.get(first);
  assert.equal(started.length,3);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, copyFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

test('TypeScript CLI binds imports from an installation path containing spaces and Chinese characters', {timeout:15000}, async t => {
  const directory = await mkdtemp(join(tmpdir(),'oce helper 中文 '));
  t.after(() => rm(directory,{recursive:true,force:true}));
  await mkdir(join(directory,'node_modules'));
  await symlink(resolve('node_modules/typescript'),join(directory,'node_modules/typescript'),
    process.platform === 'win32' ? 'junction' : 'dir');
  const script = join(directory,'typescript helper 中文.mjs');
  await copyFile('src/retrieval/languages/typescript.mjs',script);
  const output = new Promise((resolveOutput,reject) => {
    const child = execFile(process.execPath,[script],{encoding:'utf8',timeout:10000},
      (error,stdout) => error ? reject(error) : resolveOutput(stdout));
    child.stdin.on('error',reject);
    child.stdin.end(JSON.stringify({files:[
      {path:'目录/store.ts',text:'export function save() { return "中文"; }\n'},
      {path:'目录/main.ts',text:'import { save } from "./store";\nexport function run() { return save(); }\n'},
    ]}));
  });
  const {units} = JSON.parse(await output);
  assert.ok(units.some(unit => unit.text.includes('中文')));
  const run = units.find(unit => unit.name === 'run');
  assert.ok(run.relations.some(relation => relation.kind === 'calls' && units[relation.target].name === 'save'));
});

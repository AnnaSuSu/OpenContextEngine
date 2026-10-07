import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, copyFile, symlink, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { run, venvPython } from '../src/runtime.mjs';
import { python } from './helpers/live-service.mjs';

test('Windows runtime probes launch without a console window',
  {skip:process.platform !== 'win32' || !python, timeout:15000}, async () => {
    const {stdout} = await run(python, ['-c',
      'import ctypes; print(bool(ctypes.windll.kernel32.GetConsoleWindow()))'], {timeout:10000});
    assert.equal(stdout.trim(), 'False');
  });

test('Windows venv probes preserve isolated packages and launch without a console',
  {skip:process.platform !== 'win32' || !python, timeout:15000}, async t => {
    const directory = await mkdtemp(join(tmpdir(), 'oce venv 中文 '));
    t.after(() => rm(directory, {recursive:true, force:true}));
    await run(python, ['-m', 'venv', '--without-pip', directory], {timeout:10000});
    await writeFile(join(directory, 'Lib', 'site-packages', 'oce_window_fixture.py'), 'value = "venv-only"\n');
    const {stdout} = await run(venvPython(directory), ['-c',
      'import ctypes, json, sys, oce_window_fixture; print(json.dumps([bool(ctypes.windll.kernel32.GetConsoleWindow()), sys.prefix, sys.executable, oce_window_fixture.value]))'],
      {timeout:10000});
    const [console, prefix, executable, value] = JSON.parse(stdout);
    assert.equal(console, false);
    assert.equal(prefix.toLowerCase(), directory.toLowerCase());
    assert.equal(executable.toLowerCase(), venvPython(directory).toLowerCase());
    assert.equal(value, 'venv-only');
  });

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

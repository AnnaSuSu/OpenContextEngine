import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, mkdir, writeFile, readFile, stat, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname, delimiter } from 'node:path';
import { loadEnvironment, readUserConfig, saveUserConfig } from '../src/config.mjs';
import { ensureRuntime, defaultPython, venvPython, pythonInvocation } from '../src/runtime.mjs';
import { setup, validateModels } from '../src/setup.mjs';

const models = {EMBEDDING_BASE_URL:'https://embedding.example/v1',EMBEDDING_API_KEY:'embedding-test-secret',
  EMBEDDING_MODEL:'embedding-test',OCE_EMBEDDING_DIMENSIONS:'1024',RERANK_BASE_URL:'https://rerank.example/v1',
  RERANK_API_KEY:'rerank-test-secret',RERANK_MODEL:'rerank-test'};

test('Windows venv launch bypasses the redirector while preserving its interpreter and environment', async t => {
  const {dir} = await temporary(t);
  const base = join(dir, 'base Python 中文'), venv = join(dir, 'venv 中文');
  await mkdir(base); await mkdir(join(venv, 'Scripts'), {recursive:true});
  const launcher = join(venv, 'Scripts', 'python.exe'), executable = join(base, 'python.exe');
  await writeFile(launcher, 'fixture'); await writeFile(executable, 'fixture');
  await writeFile(join(venv, 'pyvenv.cfg'), `home = ${base}\r\ninclude-system-site-packages = false\r\n`);
  const env = {Path:join(venv, 'Scripts') + delimiter + base, KEEP:'value'};
  for (const command of [launcher, 'python', 'python.exe']) {
    assert.deepEqual(pythonInvocation(command, env, 'win32'),
      {command:executable, env:{...env, __PYVENV_LAUNCHER__:launcher}});
  }
  assert.ok(!('__PYVENV_LAUNCHER__' in env));
  for (const platform of ['darwin', 'linux']) {
    assert.deepEqual(pythonInvocation(launcher, env, platform), {command:launcher, env});
  }
  assert.deepEqual(pythonInvocation(executable, env, 'win32'), {command:executable, env});
  assert.deepEqual(pythonInvocation('git', env, 'win32'), {command:'git', env});
  await rm(executable);
  assert.deepEqual(pythonInvocation(launcher, env, 'win32'), {command:launcher, env});
});

test('Provider embedding batch size is validated and preserved in shared config', async t => {
  const {environment} = await temporary(t);
  const configured = {...models,OCE_EMBEDDING_BATCH_SIZE:'20',OCE_RERANK_API:'dashscope'};
  assert.doesNotThrow(() => validateModels(configured));
  saveUserConfig(configured,environment);
  assert.equal(readUserConfig(environment).OCE_EMBEDDING_BATCH_SIZE,'20');
  for (const value of ['0','65','NaN','1.5','']) {
    assert.throws(() => validateModels({...models,OCE_EMBEDDING_BATCH_SIZE:value}),/batch size/);
  }
});
test('Embedding concurrency defaults to serial and validates saved settings', async t => {
  const {environment} = await temporary(t);
  assert.doesNotThrow(() => validateModels(models));
  for (const value of ['1','2','8']) {
    const configured = {...models,OCE_EMBEDDING_CONCURRENCY:value};
    assert.doesNotThrow(() => validateModels(configured));
    saveUserConfig(configured,environment);
    assert.equal(readUserConfig(environment).OCE_EMBEDDING_CONCURRENCY,value);
  }
  for (const value of ['0','9','NaN','1.5','']) {
    assert.throws(() => validateModels({...models,OCE_EMBEDDING_CONCURRENCY:value}),/concurrency/);
  }
});
async function temporary(t) {
  const dir = await mkdtemp(join(tmpdir(),'oce-setup-'));
  t.after(() => rm(dir,{recursive:true,force:true}));
  return {dir,environment:{OCE_CONFIG_HOME:join(dir,'config')}};
}

test('Shared config uses private atomic files and explicit environment wins over saved settings and checkout defaults', async t => {
  const {dir,environment} = await temporary(t);
  const path = saveUserConfig({...models,GPT_API_KEY:'do-not-save'},environment);
  if (process.platform !== 'win32') {
    assert.equal((await stat(path)).mode & 0o777,0o600);
    assert.equal((await stat(environment.OCE_CONFIG_HOME)).mode & 0o777,0o700);
  }
  assert.ok(!('GPT_API_KEY' in readUserConfig(environment)));
  const checkout = join(dir,'checkout'); await mkdir(checkout);
  await writeFile(join(checkout,'.env'),'RERANK_MODEL=checkout\nREPONERVE_POLL_SECONDS=2\n');
  assert.equal(loadEnvironment(environment,checkout).RERANK_MODEL,models.RERANK_MODEL);
  const merged = loadEnvironment({...environment,RERANK_MODEL:'process',OCE_POLL_SECONDS:'5'},checkout);
  assert.equal(merged.RERANK_MODEL,'process');
  assert.equal(merged.OCE_POLL_SECONDS,'5');
  assert.equal(merged.EMBEDDING_MODEL,models.EMBEDDING_MODEL);
  saveUserConfig({...models,RERANK_MODEL:'updated'},environment);
  assert.equal(readUserConfig(environment).RERANK_MODEL,'updated');
  assert.deepEqual(await readdir(environment.OCE_CONFIG_HOME),['config.json']);
});

test('Malformed shared config errors never echo file contents or secrets', async t => {
  const {environment} = await temporary(t);
  await mkdir(environment.OCE_CONFIG_HOME);
  const path = join(environment.OCE_CONFIG_HOME,'config.json');
  await writeFile(path,'SECRET invalid JSON');
  assert.throws(() => readUserConfig(environment),error => /Invalid OpenContextEngine/.test(error.message) && !error.message.includes('SECRET'));
  await writeFile(path,JSON.stringify({schemaVersion:1,env:{RERANK_API_KEY:123}}));
  assert.throws(() => readUserConfig(environment),/Invalid OpenContextEngine/);
});

test('Runtime installation is isolated, reused on repeat setup and rebuilt when requirements change', async t => {
  const {environment} = await temporary(t);
  const calls = [];
  const execute = async (command,args) => {calls.push([command,args]); return {stdout:'3.14.6\n'};};
  const runtime = await ensureRuntime(environment,{execute});
  assert.ok(runtime.OCE_PYTHON.startsWith(join(environment.OCE_CONFIG_HOME,'runtimes')));
  assert.equal(calls.filter(([,args]) => args.includes('venv')).length,1);
  assert.equal(calls.filter(([,args]) => args.includes('pip')).length,1);
  const again = await ensureRuntime({...environment,...runtime},{execute});
  assert.deepEqual(again,runtime);
  assert.equal(calls.filter(([,args]) => args.includes('pip')).length,1);
  await writeFile(join(dirname(dirname(runtime.OCE_PYTHON)),'ready.json'),JSON.stringify({requirementsSha256:'old'}));
  const upgraded = await ensureRuntime({...environment,...runtime},{execute});
  assert.notEqual(upgraded.OCE_PYTHON,runtime.OCE_PYTHON);
  assert.equal(calls.filter(([,args]) => args.includes('pip')).length,2);
});

test('Windows setup installs and reuses Scripts/python.exe, preserving an explicit interpreter', async t => {
  const {dir,environment} = await temporary(t);
  environment.OCE_CONFIG_HOME = join(dir,'settings with spaces 中文');
  const calls = [];
  const execute = async (command,args) => {calls.push([command,args]); return {stdout:'3.12.0\n'};};
  const logs = [];
  const result = await setup({platform:'win32',environment:{...environment,...models},
    nonInteractive:true,execute,log:line => logs.push(line)});
  assert.equal(calls.find(([,args]) => args.includes('venv'))[0],'python');
  assert.equal(result.env.OCE_PYTHON,
    join(dirname(dirname(result.env.OCE_PYTHON)),'Scripts','python.exe'));
  assert.equal(calls.find(([,args]) => args.includes('pip'))[0],result.env.OCE_PYTHON);
  const repeated = await setup({platform:'win32',environment:{...environment,...models},
    nonInteractive:true,execute,log:()=>{}});
  assert.equal(repeated.env.OCE_PYTHON,result.env.OCE_PYTHON);
  assert.equal(calls.filter(([,args]) => args.includes('venv')).length,1);
  const explicit = join(dir,'custom python','python.exe');
  const selected = await setup({platform:'win32',python:explicit,environment:{...environment,...models},
    nonInteractive:true,execute,log:()=>{}});
  assert.notEqual(selected.env.OCE_PYTHON,result.env.OCE_PYTHON);
  assert.equal(calls.filter(([,args]) => args.includes('venv')).at(-1)[0],explicit);
  assert.ok(!logs.join('\n').includes(models.EMBEDDING_API_KEY));
  for (const platform of ['darwin','linux']) {
    assert.equal(defaultPython(platform),'python3');
    assert.equal(venvPython(dir,platform),join(dir,'bin','python'));
  }
});

test('Failed dependency install removes only its new runtime and keeps the existing configuration', async t => {
  const {environment} = await temporary(t);
  saveUserConfig(models,environment);
  const before = await readFile(join(environment.OCE_CONFIG_HOME,'config.json'),'utf8');
  const execute = async (_,args) => {if (args.includes('pip')) throw new Error('offline'); return {stdout:''};};
  await assert.rejects(ensureRuntime(environment,{execute}),/offline/);
  assert.deepEqual(await readdir(join(environment.OCE_CONFIG_HOME,'runtimes')),[]);
  assert.equal(await readFile(join(environment.OCE_CONFIG_HOME,'config.json'),'utf8'),before);
});

test('Setup saves reusable model and runtime settings without printing keys', async t => {
  const {environment} = await temporary(t);
  const logs = [];
  const result = await setup({environment:{...environment,...models},nonInteractive:true,
    execute:async () => ({stdout:'git version fixture'}),
    install:async () => ({OCE_PYTHON:'/isolated/bin/python',TIKTOKEN_CACHE_DIR:'/isolated/tokenizer'}),
    log:line => logs.push(line)});
  assert.equal(readUserConfig(environment).OCE_PYTHON,'/isolated/bin/python');
  assert.equal(readUserConfig(environment).RERANK_API_KEY,models.RERANK_API_KEY);
  assert.equal(result.path,join(environment.OCE_CONFIG_HOME,'config.json'));
  assert.ok(!logs.join('\n').includes(models.RERANK_API_KEY));
  assert.ok(!logs.join('\n').includes(models.EMBEDDING_API_KEY));
});

test('Interactive setup masks key questions and keeps prior secrets on empty input', async t => {
  const {environment} = await temporary(t);
  const questions = []; let closed = false;
  const result = await setup({environment:{...environment,...models},
    prompt:{async ask(label,current,secret) {questions.push({label,secret}); return current;}, close() {closed=true;}},
    execute:async () => ({stdout:''}),install:async () => ({OCE_PYTHON:'/isolated/bin/python'}),log:()=>{}});
  assert.equal(questions.filter(q => q.secret).length,2);
  assert.ok(closed);
  assert.equal(result.env.RERANK_API_KEY,models.RERANK_API_KEY);
});

test('Setup validates models before installing and does not overwrite saved configuration on failure', async t => {
  const {environment} = await temporary(t);
  saveUserConfig(models,environment);
  const before = readUserConfig(environment);
  await assert.rejects(setup({environment:{...environment,...models,RERANK_BASE_URL:'http://unsafe.example/v1'},
    nonInteractive:true,install:async () => assert.fail('Must not install'),log:()=>{}}),/remote HTTPS/);
  assert.deepEqual(readUserConfig(environment),before);
  for (const value of ['0','NaN','1.5','']) assert.throws(() => validateModels({...models,OCE_EMBEDDING_DIMENSIONS:value}));
});

test('Setup persists explicit HTTP opt-in and native vector dimensions for subsequent launches', async t => {
  const {environment} = await temporary(t);
  await setup({environment:{...environment,...models,OCE_ALLOW_HTTP:'1',OCE_EMBEDDING_DIMENSIONS:'2560',
    EMBEDDING_BASE_URL:'http://embedding.example:8079/v1',RERANK_BASE_URL:'http://rerank.example:8078'},
    nonInteractive:true,execute:async () => ({stdout:''}),
    install:async () => ({OCE_PYTHON:'/isolated/bin/python'}),log:()=>{}});
  const saved = readUserConfig(environment);
  assert.equal(saved.OCE_ALLOW_HTTP,'1');
  assert.equal(saved.OCE_EMBEDDING_DIMENSIONS,'2560');
  assert.equal(saved.RERANK_BASE_URL,'http://rerank.example:8078');
  assert.doesNotThrow(() => validateModels(saved));
});

test('Setup saves both SSH forwards and rejects ambiguous reranker transport before installation', async t => {
  const {environment} = await temporary(t);
  const ssh = {EMBEDDING_SSH_TUNNEL_URL:'http://127.0.0.1:43079/v1',EMBEDDING_SSH_REMOTE:'operator@models.example:22',
    RERANK_SSH_TUNNEL_URL:'http://127.0.0.1:43078/v1',RERANK_SSH_REMOTE:'operator@models.example:22'};
  const env = {...environment,...models,...ssh};
  await setup({environment:env,nonInteractive:true,execute:async () => ({stdout:''}),
    install:async () => ({OCE_PYTHON:'/isolated/bin/python'}),log:()=>{}});
  const saved = readUserConfig(environment);
  for (const [key,value] of Object.entries(ssh)) assert.equal(saved[key],value);
  await assert.rejects(setup({environment:{...env,RERANK_REMOTE_RUNTIME_URL:'http://127.0.0.1:8000/v1'},
    nonInteractive:true,install:async () => assert.fail('Must not install'),log:()=>{}}),/Choose either/);
  assert.deepEqual(readUserConfig(environment),saved);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, rm, readFile, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
const execute = promisify(execFile);

test('npm package contains the runtime and excludes credentials, caches, benchmarks, and development SDKs', async t => {
  const cache = await mkdtemp(join(tmpdir(),'oce-pack-'));
  t.after(() => rm(cache,{recursive:true,force:true}));
  const result = await execute('npm',['pack','--dry-run','--json','--ignore-scripts','--cache',cache]);
  const [pack] = JSON.parse(result.stdout), files = new Set(pack.files.map(file => file.path));
  for (const path of ['LICENSE','README.md','README.zh-CN.md','bin/opencontextengine.mjs','src/config.mjs','src/runtime.mjs','src/setup.mjs',
    'src/mcp.mjs','src/workspaces.mjs','src/shared-service.mjs','src/retrieval/shared_worker.py','src/eval/remote-models.mjs','scripts/mcp-opencontextengine.mjs',
    'scripts/retrieval-server.py','src/retrieval/languages/typescript.mjs','src/retrieval/languages/go_ast.go',
    'src/retrieval/languages/go_types.go','src/retrieval/reranker.py','src/retrieval/writer_lock.py',
    'requirements.txt']) assert.ok(files.has(path),path);
  for (const path of files) {
    assert.doesNotMatch(path,/(^|\/)(\.env[^/]*|\.pilot-state|node_modules|__pycache__)(\/|$)|\.pyc$/);
    assert.doesNotMatch(path,/^(tests|eval|deploy)\//);
  }
  assert.ok(!files.has('package-lock.json')); // npm omits lockfiles; installed workers must handle this.
  assert.ok(pack.files.find(file => file.path === 'bin/opencontextengine.mjs').mode & 0o111);
  const metadata = JSON.parse(await readFile('package.json'));
  assert.equal(metadata.name,'open-context-engine');
  assert.equal(pack.filename,'open-context-engine-0.1.3.tgz');
  assert.equal(metadata.bin['open-context-engine'],'bin/opencontextengine.mjs');
  assert.equal(metadata.bin.opencontextengine,'bin/opencontextengine.mjs');
  assert.notEqual(metadata.private,true);
  assert.equal(metadata.license,'MIT');
  assert.deepEqual(metadata.os,['darwin','linux','win32']);
  assert.deepEqual(metadata.publishConfig,{access:'public',registry:'https://registry.npmjs.org/'});
  assert.ok(!metadata.dependencies['@augmentcode/auggie-sdk']);
  assert.ok(!metadata.dependencies['@openai/codex-sdk']);
});

test('CLI help, version, and generated MCP configuration work outside the source checkout without exposing keys', async t => {
  const dir = await mkdtemp(join(tmpdir(),'oce-cli-'));
  t.after(() => rm(dir,{recursive:true,force:true}));
  const bin = resolve('bin/opencontextengine.mjs');
  const options = {cwd:dir,env:{...process.env,OCE_CONFIG_HOME:join(dir,'config'),RERANK_API_KEY:'never-print-this-secret'}};
  const help = await execute(process.execPath,[bin,'--help'],options);
  assert.match(help.stdout,/open-context-engine setup/);
  const version = await execute(process.execPath,[bin,'--version'],options);
  assert.match(version.stdout,/^0\.1\.3\n$/);
  const config = await execute(process.execPath,[bin,'mcp-config'],options);
  const server = JSON.parse(config.stdout).mcpServers['open-context-engine'];
  assert.equal(server.command,process.execPath);
  assert.deepEqual(server.args,[bin,'mcp']);
  assert.equal(server.env.OCE_CONFIG_HOME,options.env.OCE_CONFIG_HOME);
  assert.doesNotMatch(config.stdout,/never-print-this-secret/);
  const relative = await execute(process.execPath,[bin,'mcp-config'],{...options,env:{...options.env,OCE_CONFIG_HOME:'settings'}});
  assert.equal(JSON.parse(relative.stdout).mcpServers['open-context-engine'].env.OCE_CONFIG_HOME,join(await realpath(dir),'settings'));
  await assert.rejects(execute(process.execPath,[bin,'not-a-command'],options));
});


test('release archive explicitly selects the English README while keeping the translation', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'oce-release-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const { stdout } = await execute(process.execPath, ['scripts/pack-release.mjs', dir]);
  const [pack] = JSON.parse(stdout);
  const archive = join(dir, pack.filename);
  const { stdout: metadata } = await execute('tar', ['-xOf', archive, 'package/package.json']);
  const manifest = JSON.parse(metadata);
  assert.equal(manifest.readmeFilename, 'README.md');
  assert.equal(manifest.readme, await readFile('README.md', 'utf8'));
  const { stdout: translated } = await execute('tar', ['-xOf', archive, 'package/README.zh-CN.md']);
  assert.equal(translated, await readFile('README.zh-CN.md', 'utf8'));
});

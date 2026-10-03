import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { resolve, dirname } from 'node:path';
import { projectRoot } from '../src/pilot/config.mjs';
import { sha256 } from '../src/eval/evidence.mjs';
import { renderBlocks, cocoBlocks, contextWeaverBlocks } from '../src/eval/normalize.mjs';
import { remoteRerankerConfig, embeddingTransportConfig } from '../src/eval/remote-models.mjs';
import os from 'node:os';

const engine = process.argv[2];
if (!['cocoindex', 'contextweaver'].includes(engine)) throw new Error('Usage: node scripts/run-baseline.mjs cocoindex|contextweaver [--dry-run]');
const localEnv = existsSync(resolve(projectRoot, '.env')) ? parseEnv(readFileSync(resolve(projectRoot, '.env'), 'utf8')) : {};
const reranker = engine === 'contextweaver' ? remoteRerankerConfig({ ...localEnv, ...process.env }) : null;
const research = process.env.BASELINE_RESEARCH_ROOT ?? '/private/tmp/reponerve-research-20261003-r7s_jlis';
const toolRoot = resolve(research, engine === 'cocoindex' ? 'cocoindex-code' : 'ContextWeaver');
const toolSha = engine === 'cocoindex' ? '8ec0ff3510be526e699028db5b64e10a0a8359b3' : '42375d315e180da258ebb983215004dbbf98c00d';
if (execFileSync('git', ['rev-parse', 'HEAD'], { cwd: toolRoot, encoding: 'utf8' }).trim() !== toolSha) throw new Error('Unexpected baseline revision');
if (execFileSync('git', ['diff', 'HEAD', '--', 'src', 'package.json', 'pnpm-lock.yaml', 'pyproject.toml'], { cwd: toolRoot, encoding: 'utf8' }).trim()) throw new Error('Baseline source has local modifications');
const dataset = resolve(projectRoot, 'eval/django-v1');
const snapshot = JSON.parse(readFileSync(resolve(dataset, 'snapshot.json')));
const queries = JSON.parse(readFileSync(resolve(dataset, 'queries.json')));
const original = resolve(projectRoot, '.pilot-state/django-v1/corpus');
const state = resolve(projectRoot, '.pilot-state/baselines', engine);
const corpus = resolve(state, 'corpus');
mkdirSync(corpus, { recursive: true });
for (const file of snapshot.files) {
  const data = readFileSync(resolve(original, file.path));
  if (sha256(data) !== file.sha256) throw new Error('Source hash mismatch');
  const target = resolve(corpus, file.path); mkdirSync(dirname(target), { recursive: true }); writeFileSync(target, data);
}
const python = resolve(projectRoot, '.pilot-state/baselines/cocoindex-venv/bin/python');
const config = { engine, toolSha, commit: snapshot.commit, files: snapshot.files.length,
  embedding: { model: 'Qwen3-Embedding-4B', dimensions: 1024, upstreamMaxInputTokens: 1024,
    instruction: 'unmodified upstream tool text; no external query rewrite', requestBatchSize: 8, transportMaxAttemptsPerBatch: 3, transportAttemptTimeoutMs: 30000,
    maxRequests: 6000, maxInputChars: 60_000_000 },
  search: engine === 'cocoindex' ? { limit: 60, chunking: 'unmodified upstream defaults' }
    : { configuration: 'upstream retrieval defaults; embedding client configured for actual service input window', embeddingsMaxContextTokens: 1024,
      reranker: { baseUrl: reranker.baseUrl, model: reranker.model, deployment: 'remote-only' } },
  answerVersion: 'v2', primaryBudgetTokens: 4000, formatting: 'Path headers and line numbers; native text and order unchanged',
  maxIndexAndFirstQueryMs: 5400000, maxSubsequentQueryMs: 120000, maxTotalMs: 6000000 };
config.nodeVersion = process.version;
config.embedding.transport = embeddingTransportConfig({ ...localEnv, ...process.env });
config.executionHost = { platform: process.platform, architecture: process.arch, hostname: os.hostname(), location: process.env.BASELINE_EXECUTION_LOCATION ?? 'local-client' };
config.harnessSha256 = Object.fromEntries(['scripts/run-baseline.mjs', 'scripts/coco-baseline.py', 'scripts/embedding-gateway.mjs', 'scripts/baseline-home.mjs', 'src/eval/normalize.mjs', 'src/eval/remote-models.mjs', 'src/eval/embedding-transport.mjs'].map(name => [name, sha256(readFileSync(resolve(projectRoot, name)))]));
if (engine === 'cocoindex' && !existsSync(python)) throw new Error('Baseline client environment was removed during local-model cleanup. Recreate remote-client dependencies only before running.');
config.dependencies = engine === 'cocoindex'
  ? JSON.parse(execFileSync(python, ['-c', "import json,importlib.metadata as m; print(json.dumps({x:m.version(x) for x in ['cocoindex','cocoindex-code','sqlite-vec','numpy','litellm']}))"], { encoding: 'utf8' }))
  : { lockfileSha256: sha256(readFileSync(resolve(toolRoot, 'pnpm-lock.yaml'))) };
if (process.argv.includes('--dry-run')) { console.log(JSON.stringify(config, null, 2)); process.exit(0); }
const run = resolve(projectRoot, `runs/${engine}-django-${new Date().toISOString().replace(/:/g, '-')}`);
mkdirSync(run, { recursive: true, mode: 0o700 });
for (const name of Object.keys(config.harnessSha256)) {
  const target = resolve(run, 'harness', name); mkdirSync(dirname(target), { recursive: true }); copyFileSync(resolve(projectRoot, name), target);
}
for (const name of ['snapshot.json', 'queries.json', 'answers.v1.json', 'answers.v2.json', 'protocol.json', 'freeze.json']) {
  // Remote retrieval workers do not need labels. Copy them only where present;
  // offline scoring attaches the frozen local reference after retrieval ends.
  if (name.startsWith('answers.') && !existsSync(resolve(dataset, name))) continue;
  copyFileSync(resolve(dataset, name), resolve(run, name));
}
const tasks = queries.cases.flatMap((q, i) => (i % 2 ? ['en', 'zh'] : ['zh', 'en']).map(language => ({ id: q.id, language, query: q.queries[language] })));
const report = { schemaVersion: 1, kind: 'development-pilot', system: engine, startedAt: new Date().toISOString(),
  config, results: [], status: 'running', stage: 'gateway' };
const save = () => writeFileSync(resolve(run, 'report.json'), JSON.stringify(report, null, 2)+'\n', { mode: 0o600 });
save(); console.log(JSON.stringify({ run, config }));
const started = Date.now();
const childEnv = { PATH: process.env.PATH, LANG: 'en_US.UTF-8', PYTHONUNBUFFERED: '1', TOKENIZERS_PARALLELISM: 'false' };
for (const name of ['EMBEDDING_SSH_TUNNEL_URL', 'EMBEDDING_SSH_REMOTE']) {
  if (process.env[name]) childEnv[name] = process.env[name];
}
const children = new Set();
function start(command, args, options = {}) {
  const child = spawn(command, args, { cwd: projectRoot, env: childEnv, stdio: ['pipe', 'pipe', 'pipe'], ...options });
  children.add(child); child.once('exit', () => children.delete(child)); return child;
}
function stopAll() { for (const child of children) child.kill('SIGTERM'); }
const totalTimer = setTimeout(() => { report.error = 'Whole-run deadline'; stopAll(); }, config.maxTotalMs);
const heartbeat = setInterval(() => {
  const gatewayFile = resolve(run, 'gateway.json');
  if (existsSync(gatewayFile)) {
    const gateway = JSON.parse(readFileSync(gatewayFile, 'utf8'));
    if (gateway.failures) { report.error = `Embedding gateway failed: ${gateway.firstFailure?.message ?? 'transport failure'}`; stopAll(); }
  }
  console.log(JSON.stringify({ stage: report.stage, completed: report.results.length, elapsedMs: Date.now()-started }));
}, 30000);
process.once('SIGTERM', () => { report.status = 'interrupted'; report.elapsedMs = Date.now()-started; save(); stopAll(); process.exit(143); });

try {
  const gateway = start(process.execPath, [resolve(projectRoot, 'scripts/embedding-gateway.mjs'), resolve(run, 'gateway.json')]);
  let gatewayLog = ''; gateway.stderr.on('data', x => { gatewayLog += x; writeFileSync(resolve(run, 'gateway.stderr.txt'), gatewayLog); });
  const gatewayUrl = await new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error('Gateway startup deadline')), 10000);
    gateway.once('error', fail); gateway.once('exit', () => { clearTimeout(timer); fail(new Error('Embedding gateway failed to start; check project EMBEDDING_API_KEY configuration')); });
    let text = ''; gateway.stdout.on('data', chunk => { text += chunk; const line = text.split('\n')[0];
      if (line && text.includes('\n')) { try { const row = JSON.parse(line); if (row.listening) { clearTimeout(timer); ok(row.listening); } } catch {} }
    });
  });
  report.stage = 'indexing'; save();
  if (engine === 'cocoindex') {
    const child = start(python, [resolve(projectRoot, 'scripts/coco-baseline.py'), corpus, resolve(dataset, 'queries.json'), run], { env: { ...childEnv, BASELINE_EMBEDDING_URL: gatewayUrl } });
    let stdout = '', stderr = '';
    child.stdout.on('data', x => { stdout += x; writeFileSync(resolve(run, 'native.stdout.txt'), stdout); console.log(x.toString().trim()); });
    child.stderr.on('data', x => { stderr += x; writeFileSync(resolve(run, 'native.stderr.txt'), stderr); });
    const code = await new Promise((ok, fail) => { child.once('error', fail); child.once('exit', ok); });
    const native = JSON.parse(readFileSync(resolve(run, 'native-report.json')));
    report.indexingMs = native.indexingMs; report.indexStatus = native.indexStatus;
    for (const row of native.results) {
      const data = JSON.parse(readFileSync(resolve(run, row.nativeFile)));
      const raw = renderBlocks(cocoBlocks(data), corpus); const rawFile = `${row.id}.${row.language}.txt`;
      writeFileSync(resolve(run, rawFile), raw); report.results.push({ ...row, rawFile, sha256: sha256(raw) });
    }
    if (code !== 0) throw new Error(native.error ?? `CocoIndex exited ${code}`);
  } else {
    const home = resolve(state, 'user-state'); mkdirSync(home, { recursive: true });
    const env = { ...childEnv, BASELINE_STATE_DIR: home, NODE_ENV: 'test', EMBEDDINGS_PROVIDER: 'remote',
      EMBEDDINGS_BASE_URL: gatewayUrl, EMBEDDINGS_API_KEY: 'local-only', EMBEDDINGS_MODEL: 'Qwen3-Embedding-4B',
      EMBEDDINGS_DIMENSIONS: '1024', EMBEDDINGS_MAX_CONCURRENCY: '1', EMBEDDINGS_MAX_CONTEXT_TOKENS: '1024',
      RERANK_BASE_URL: reranker.baseUrl, RERANK_API_KEY: reranker.apiKey, RERANK_MODEL: reranker.model };
    const child = start(process.execPath, ['--import', resolve(projectRoot, 'scripts/baseline-home.mjs'), resolve(toolRoot, 'dist/index.js'), 'search', '--repo-path', corpus, '--jsonl'], { env });
    let buffer = '', stderr = '', previous = Date.now(), index = 0;
    let deadline = setTimeout(() => child.kill('SIGTERM'), config.maxIndexAndFirstQueryMs);
    child.stderr.on('data', x => { stderr += x; writeFileSync(resolve(run, 'native.stderr.txt'), stderr); });
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      buffer += chunk;
      for (;;) {
        const end = buffer.indexOf('\n'); if (end < 0) break;
        const line = buffer.slice(0, end); buffer = buffer.slice(end+1); if (!line.trim()) continue;
        try {
          const data = JSON.parse(line); const task = tasks[index++]; if (!task) throw new Error('Unexpected extra output');
          const nativeFile = `${task.id}.${task.language}.native.json`; writeFileSync(resolve(run, nativeFile), line+'\n');
          if (data.error) throw new Error(data.error);
          if (data.query !== task.query) throw new Error('Returned query order mismatch');
          const raw = renderBlocks(contextWeaverBlocks(data), corpus); const rawFile = `${task.id}.${task.language}.txt`;
          writeFileSync(resolve(run, rawFile), raw);
          const now = Date.now(); report.results.push({ ...task, status: 'completed', nativeFile, rawFile, sha256: sha256(raw),
            elapsedMs: data.debug?.timingMs?.total ?? now-previous, timingScope: 'native search service; excludes initialization' });
          if (index === 1) report.indexAndFirstQueryMs = now-started;
          previous = now; report.stage = 'querying'; save(); console.log(JSON.stringify({ completed: index, id: task.id, language: task.language }));
          clearTimeout(deadline); deadline = setTimeout(() => child.kill('SIGTERM'), config.maxSubsequentQueryMs);
        } catch (error) { report.error = String(error.message).slice(0, 1500); child.kill('SIGTERM'); }
      }
    });
    child.stdin.end(tasks.map(task => JSON.stringify({ information_request: task.query })).join('\n')+'\n');
    const code = await new Promise((ok, fail) => { child.once('error', fail); child.once('exit', ok); });
    clearTimeout(deadline);
    if (code !== 0 || report.error || report.results.length !== tasks.length) throw new Error(report.error ?? `ContextWeaver incomplete, exit ${code}`);
  }
  report.status = 'completed';
} catch (error) {
  report.status = 'failed'; report.error ??= String(error.message).slice(0, 1500); process.exitCode = 1;
} finally {
  clearTimeout(totalTimer); clearInterval(heartbeat); stopAll(); report.elapsedMs = Date.now()-started; save();
  console.log(JSON.stringify({ status: report.status, completed: report.results.length, run, error: report.error }));
}

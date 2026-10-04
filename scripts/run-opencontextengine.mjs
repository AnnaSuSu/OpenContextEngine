import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { resolve, dirname } from 'node:path';
import os from 'node:os';
import { projectRoot } from '../src/pilot/config.mjs';
import { sha256 } from '../src/eval/evidence.mjs';
import { remoteRerankerConfig, embeddingTransportConfig, rerankerExecutionTransport } from '../src/eval/remote-models.mjs';

const env = { ...parseEnv(readFileSync(resolve(projectRoot, '.env'), 'utf8')), ...process.env };
const reranker = remoteRerankerConfig(env);
const transport = embeddingTransportConfig(env);
const rerankTransport = rerankerExecutionTransport(env);
const mode = process.argv[2] ?? 'batched';
if (!['cascade', 'entity', 'batched', 'baseline'].includes(mode)) throw new Error('Usage: node scripts/run-opencontextengine.mjs [batched|cascade|entity|baseline]');
const system = mode === 'cascade' ? 'reponerve-cascade' : mode === 'entity' ? 'reponerve-entity' : mode === 'batched' ? 'reponerve-batched' : 'reponerve-v1-direct';
const run = resolve(projectRoot, `runs/${system}-django-${new Date().toISOString().replace(/:/g, '-')}`);
mkdirSync(run, { recursive: true });
const dataset = resolve(projectRoot, 'eval/django-v1');
for (const name of ['snapshot.json', 'queries.json', 'answers.v1.json', 'answers.v2.json', 'protocol.json', 'freeze.json']) {
  if (existsSync(resolve(dataset, name))) copyFileSync(resolve(dataset, name), resolve(run, name));
}
copyFileSync(resolve(projectRoot, '.pilot-state/reponerve/plans.json'), resolve(run, 'plans.json'));
const plans = JSON.parse(readFileSync(resolve(run, 'plans.json')));
const tasks = JSON.parse(readFileSync(resolve(run, 'queries.json'))).cases;
if (plans.queriesSha256 !== sha256(readFileSync(resolve(run, 'queries.json'))) || plans.results.length !== tasks.length * 2 ||
    tasks.some(q => ['zh', 'en'].some(language => plans.results.filter(r => r.id === q.id && r.language === language && r.query === q.queries[language]).length !== 1))) throw new Error('Plans do not match frozen queries');
const sources = ['src/retrieval/engine.py', 'src/retrieval/languages/__init__.py', 'src/retrieval/languages/schema.py', 'src/retrieval/languages/text.py', 'src/retrieval/languages/files.py', 'src/retrieval/languages/python.py', 'src/retrieval/languages/go.py', 'src/retrieval/languages/go_ast.go','src/retrieval/languages/go_types.go', 'src/retrieval/languages/typescript.py', 'src/retrieval/languages/typescript.mjs', 'package.json', 'package-lock.json', 'src/retrieval/cascade.py', 'src/retrieval/entities.py', 'src/retrieval/batched.py', 'src/retrieval/routed.py', 'src/eval/remote-models.mjs', 'deploy/reranker/server.py', 'scripts/opencontextengine-worker.py', 'scripts/run-opencontextengine.mjs', 'scripts/plan-retrieval.mjs', 'scripts/literal-retrieval-plans.mjs', 'scripts/embedding-gateway.mjs'];
for (const file of sources) { const out = resolve(run, 'harness', file); mkdirSync(dirname(out), { recursive: true }); copyFileSync(resolve(projectRoot, file), out); }
const report = { schemaVersion: 1, kind: 'development-pilot', system, startedAt: new Date().toISOString(),
  status: 'running', stage: 'indexing', results: [], config: { engine: mode === 'cascade' ? 'structural-cascade-v2' : mode === 'entity' ? 'entity-cascade-v3' : mode === 'batched' ? 'batched-dag-v4' : 'ast-facets-v1', primaryBudgetTokens: 4000,
    executionHost: { hostname: os.hostname(), platform: process.platform },
    embedding: { model: 'Qwen3-Embedding-4B', dimensions: 1024, transport, queryCache: false }, reranker: { model: reranker.model, ...rerankTransport },
    planner: plans.planner, plansSha256: sha256(readFileSync(resolve(run, 'plans.json'))),
    harnessSha256: Object.fromEntries(sources.map(f => [f, sha256(readFileSync(resolve(projectRoot, f)))])) } };
writeFileSync(resolve(run, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ run }));
const gateway = spawn(process.execPath, [resolve(projectRoot, 'scripts/embedding-gateway.mjs'), resolve(run, 'gateway.json')], { env, stdio: ['ignore', 'pipe', 'inherit'] });
let worker;
try {
  const url = await new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error('Gateway startup timeout')), 10000);
    gateway.once('error', fail); gateway.once('exit', () => fail(new Error('Gateway exited')));
    let buffer = '';
    gateway.stdout.on('data', data => { buffer += data; const line = buffer.split('\n')[0];
      if (buffer.includes('\n')) { const event = JSON.parse(line); if (event.listening) { clearTimeout(timer); ok(event.listening); } }
    });
  });
  worker = spawn(resolve(projectRoot, '.pilot-state/baselines/cocoindex-venv/bin/python'), [resolve(projectRoot, 'scripts/opencontextengine-worker.py')],
    { env: { ...process.env, OPENBLAS_NUM_THREADS: '2', OMP_NUM_THREADS: '2' }, stdio: ['pipe', 'inherit', 'inherit'] });
  worker.stdin.end(JSON.stringify({ run, corpus: resolve(projectRoot, '.pilot-state/django-v1/corpus'),
    state: resolve(projectRoot, '.pilot-state/reponerve/index'), embeddingUrl: url,
    embeddingQueryUrl: transport.requestBaseUrl, embeddingKey: env.EMBEDDING_API_KEY,
    engine: mode, reranker: { ...reranker, baseUrl: rerankTransport.requestBaseUrl } }) + '\n');
  const timer = setTimeout(() => worker.kill('SIGTERM'), 3600000);
  const code = await new Promise((ok, fail) => { worker.once('error', fail); worker.once('exit', ok); });
  clearTimeout(timer); if (code !== 0) process.exitCode = 1;
} finally { worker?.kill('SIGTERM'); gateway.kill('SIGTERM'); }

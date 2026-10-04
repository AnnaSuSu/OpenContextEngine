import { spawn } from 'node:child_process';
import { existsSync, realpathSync } from 'node:fs';
import { createHash, randomBytes } from 'node:crypto';
import { homedir } from 'node:os';
import { resolve, dirname, delimiter } from 'node:path';
import { createInterface } from 'node:readline';
import { projectRoot, loadEnvironment } from './config.mjs';
import { embeddingTransportConfig, remoteRerankerConfig, rerankerExecutionTransport } from './eval/remote-models.mjs';

export function serviceConfig({root, state, port = 0} = {}, environment = process.env) {
  const env = loadEnvironment(environment);
  const embedding = embeddingTransportConfig(env);
  const reranker = remoteRerankerConfig(env), runtime = rerankerExecutionTransport(env);
  const repository = root ? realpathSync(resolve(root)) : undefined;
  const workspaceId = repository && createHash('sha256').update(repository).digest('hex').slice(0, 24);
  const candidates = ['.venv/bin/python', '.pilot-state/baselines/cocoindex-venv/bin/python',
    '.pilot-state/language-adapters-venv/bin/python'].map(path => resolve(projectRoot, path));
  const currentState = repository && resolve(homedir(), '.cache/opencontextengine', workspaceId);
  const previousState = repository && resolve(homedir(), '.cache/reponerve', workspaceId);
  const defaultState = repository && (existsSync(currentState) ? currentState : existsSync(previousState) ? previousState : currentState);
  return {
    python: env.OCE_PYTHON || candidates.find(existsSync) || 'python3',
    workerEnv: {...(env.OCE_GO_BINARY ? {OCE_GO_BINARY:env.OCE_GO_BINARY} : {}),
      ...(env.TIKTOKEN_CACHE_DIR ? {TIKTOKEN_CACHE_DIR:env.TIKTOKEN_CACHE_DIR} : {})},
    config: {root: repository, state: state ? resolve(state) : repository
      ? defaultState : resolve(projectRoot, '.pilot-state/reponerve/index'),
    serviceKey: env.OCE_API_KEY || randomBytes(32).toString('hex'), port,
    embeddingUrl: embedding.requestBaseUrl, embeddingIdentity: embedding.baseUrl,
    embeddingKey: env.EMBEDDING_API_KEY,
    embeddingModel: env.EMBEDDING_MODEL || 'Qwen3-Embedding-4B',
    embeddingDimensions: Number(env.OCE_EMBEDDING_DIMENSIONS || 1024),
    embeddingRevision: env.OCE_EMBEDDING_REVISION || '1',
    reranker: {...reranker, baseUrl: runtime.requestBaseUrl},
    languageOptions: env.OCE_LANGUAGE_OPTIONS ? JSON.parse(env.OCE_LANGUAGE_OPTIONS) : {},
    pollSeconds: Number(env.OCE_POLL_SECONDS || 1),
    debounceSeconds: Number(env.OCE_DEBOUNCE_SECONDS || .3)},
  };
}

export function startService(settings, {log = line => process.stderr.write(line + '\n')} = {}) {
  const {python, config} = settings;
  const child = spawn(python, [resolve(projectRoot, 'scripts/retrieval-server.py')], {
    cwd: projectRoot, env: {...process.env, ...settings.workerEnv,
      PATH:dirname(process.execPath)+delimiter+(process.env.PATH || ''), OPENBLAS_NUM_THREADS:'2', OMP_NUM_THREADS:'2'},
    stdio:['pipe', 'pipe', 'pipe'],
  });
  const lines = createInterface({input: child.stdout});
  const errors = createInterface({input: child.stderr});
  errors.on('line', log);
  child.stdin.on('error', () => {}); // Spawn/exit handlers report early failures.
  child.stdin.end(JSON.stringify(config) + '\n');
  const ready = new Promise((resolveReady, reject) => {
    const timer = setTimeout(() => {child.kill(); reject(new Error('Retrieval worker startup timed out'));}, 15000);
    child.once('error', error => {clearTimeout(timer); reject(error);});
    child.once('exit', code => {clearTimeout(timer); reject(new Error(`Retrieval worker exited (${code})`));});
    lines.on('line', line => {
      try {
        const value = JSON.parse(line);
        if (value.listening) {
          clearTimeout(timer);
          resolveReady({baseUrl:value.listening, apiKey:config.serviceKey});
          return;
        }
      } catch { /* Non-protocol worker logs belong on stderr. */ }
      log(line);
    });
  });
  async function close() {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
    await new Promise(resolveClosed => {
      const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
      child.once('exit', () => {clearTimeout(timer); resolveClosed();});
      child.kill('SIGTERM');
    });
  }
  return {child, ready, close};
}

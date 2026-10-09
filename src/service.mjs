import { spawn } from 'node:child_process';
import { existsSync, realpathSync } from 'node:fs';
import { createHash, randomBytes } from 'node:crypto';
import { homedir } from 'node:os';
import { resolve, dirname, delimiter } from 'node:path';
import { createInterface } from 'node:readline';
import { projectRoot, loadEnvironment } from './config.mjs';
import { defaultPython, venvPython, pythonInvocation } from './runtime.mjs';
import { embeddingTransportConfig, remoteRerankerConfig, rerankerExecutionTransport } from './eval/remote-models.mjs';

export function serviceConfig({root, state, port = 0} = {}, environment = process.env) {
  const env = loadEnvironment(environment);
  const embedding = embeddingTransportConfig(env);
  const reranker = remoteRerankerConfig(env), runtime = rerankerExecutionTransport(env);
  const repository = root ? realpathSync.native(resolve(root)) : undefined;
  const workspaceId = repository && createHash('sha256').update(repository).digest('hex').slice(0, 24);
  const candidates = ['.venv', '.pilot-state/baselines/cocoindex-venv',
    '.pilot-state/language-adapters-venv'].map(path => venvPython(resolve(projectRoot, path)));
  const currentState = repository && resolve(homedir(), '.cache/opencontextengine', workspaceId);
  const previousState = repository && resolve(homedir(), '.cache/reponerve', workspaceId);
  const defaultState = repository && (existsSync(currentState) ? currentState : existsSync(previousState) ? previousState : currentState);
  return {
    python: env.OCE_PYTHON || candidates.find(existsSync) || defaultPython(),
    workerEnv: {...(env.OCE_GO_BINARY ? {OCE_GO_BINARY:env.OCE_GO_BINARY} : {}),
      ...(env.TIKTOKEN_CACHE_DIR ? {TIKTOKEN_CACHE_DIR:env.TIKTOKEN_CACHE_DIR} : {})},
    config: {root: repository, state: state ? resolve(state) : repository
      ? defaultState : resolve(projectRoot, '.pilot-state/reponerve/index'),
    serviceKey: env.OCE_API_KEY || randomBytes(32).toString('hex'), port,
    embeddingUrl: embedding.requestBaseUrl, embeddingIdentity: embedding.baseUrl,
    embeddingKey: env.EMBEDDING_API_KEY,
    embeddingModel: env.EMBEDDING_MODEL || 'Qwen3-Embedding-4B',
    embeddingDimensions: Number(env.OCE_EMBEDDING_DIMENSIONS || 1024),
    embeddingBatchSize: Number(env.OCE_EMBEDDING_BATCH_SIZE ?? 64),
    embeddingConcurrency: Number(env.OCE_EMBEDDING_CONCURRENCY ?? 1),
    embeddingRevision: env.OCE_EMBEDDING_REVISION || '1',
    reranker: {...reranker, baseUrl: runtime.requestBaseUrl},
    languageOptions: env.OCE_LANGUAGE_OPTIONS ? JSON.parse(env.OCE_LANGUAGE_OPTIONS) : {},
    pollSeconds: Number(env.OCE_POLL_SECONDS || 1),
    maxUnits: Number(env.OCE_MAX_UNITS || 200000),
    maxVectorBytes: Number(env.OCE_MAX_VECTOR_BYTES || 2147483648),
    vectorCacheBytes: Number(env.OCE_VECTOR_CACHE_BYTES || 4294967296),
    maxFiles: Number(env.OCE_MAX_FILES || 50000),
    maxSourceBytes: Number(env.OCE_MAX_SOURCE_BYTES || 268435456),
    exclude: env.OCE_EXCLUDE ? JSON.parse(env.OCE_EXCLUDE) : [],
    strictFreshness: env.OCE_STRICT_FRESHNESS === undefined ? process.platform === 'win32' : env.OCE_STRICT_FRESHNESS === '1',
    unloadIdleSeconds: Number(env.OCE_UNLOAD_IDLE_SECONDS || 120),
    maxResidentWorkers: Number(env.OCE_MAX_RESIDENT_WORKERS || 3),
    maxConcurrentBuilds: Number(env.OCE_MAX_CONCURRENT_BUILDS || 1),
    resourceDirectory: env.OCE_RESOURCE_DIRECTORY || (state ? resolve(dirname(resolve(state)), '.resources') : resolve(homedir(), '.cache/opencontextengine/resources')),
    scanIdleSeconds: Number(env.OCE_SCAN_IDLE_SECONDS || 60),
    debounceSeconds: Number(env.OCE_DEBOUNCE_SECONDS || .3)},
  };
}

export function startService(settings, {log = line => process.stderr.write(line + '\n'), startupMs = 15000} = {}) {
  const {python, config} = settings;
  const invocation = pythonInvocation(python, {...process.env, ...settings.workerEnv,
      PATH:dirname(process.execPath)+delimiter+(process.env.PATH || ''),
      PYTHONUTF8:'1', PYTHONIOENCODING:'utf-8', OPENBLAS_NUM_THREADS:'2', OMP_NUM_THREADS:'2'});
  const child = spawn(invocation.command, [resolve(projectRoot, 'scripts/retrieval-server.py')], {
    cwd: projectRoot, env: invocation.env,
    // Keep shared workers out of libuv's Windows kill-on-parent-exit job.
    // Their own helper processes must also suppress console creation.
    stdio:['pipe', 'pipe', 'pipe'], detached:Boolean(config.shared), windowsHide:true,
  });
  const lines = createInterface({input: child.stdout});
  const errors = createInterface({input: child.stderr});
  errors.on('line', log);
  child.stdin.on('error', () => {}); // Spawn/exit handlers report early failures.
  child.stdin.end(JSON.stringify(config) + '\n');
  const ready = new Promise((resolveReady, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(Object.assign(new Error('Retrieval worker startup timed out'), {code:'STARTUP_TIMEOUT'}));
    }, startupMs);
    child.once('error', error => {clearTimeout(timer); reject(error);});
    child.once('exit', code => {clearTimeout(timer); reject(new Error(`Retrieval worker exited (${code})`));});
    lines.on('line', line => {
      try {
        const value = JSON.parse(line);
        if (value.startupError) {
          clearTimeout(timer);
          const error = new Error(`Retrieval worker failed to start: ${value.startupError.message}`);
          error.code = value.startupError.code;
          reject(error);
          return;
        }
        if (value.listening) {
          clearTimeout(timer);
          if (config.shared) {
            lines.close(); errors.close();
            child.stdout.destroy(); child.stderr.destroy();
            child.unref();
          }
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

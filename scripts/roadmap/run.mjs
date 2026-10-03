// Credentials stay on the authorized model host and are passed via stdin.
import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';

if (process.platform !== 'linux') throw Error('Remote evaluation host required');
const env = { ...parseEnv(readFileSync('.env', 'utf8')), ...process.env };
if (!env.EMBEDDING_API_KEY || !env.RERANK_API_KEY) throw Error('Missing model credentials');
const config = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const script = config.script ?? 'compare.py';
if (!['compare.py', 'structure.py'].includes(script)) throw Error('Unknown evaluation script');
const child = spawn('/root/reponerve-baselines/worker/.pilot-state/baselines/cocoindex-venv/bin/python',
  [resolve('scripts/roadmap', script)], {
    env: { ...process.env, OPENBLAS_NUM_THREADS: '2', OMP_NUM_THREADS: '2' },
    stdio: ['pipe', 'inherit', 'inherit'],
  });
child.stdin.end(JSON.stringify({ ...config, embeddingUrl: 'http://127.0.0.1:42002/v1',
  embeddingKey: env.EMBEDDING_API_KEY, reranker: {
    baseUrl: 'http://127.0.0.1:23504/v1', model: 'Qwen3-Reranker-4B', apiKey: env.RERANK_API_KEY,
  } })+'\n');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => { process.exitCode = code ?? 1; });

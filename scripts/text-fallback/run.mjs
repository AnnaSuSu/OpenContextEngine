// Run only on the already configured remote evaluation host; no local models.
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { parseEnv } from 'node:util';
import { resolve } from 'node:path';
import { projectRoot } from '../../src/pilot/config.mjs';

if (process.platform !== 'linux') throw new Error('This smoke runner requires the configured Linux evaluation host');
const env = { ...parseEnv(readFileSync(resolve(projectRoot, '.env'), 'utf8')), ...process.env };
if (!env.EMBEDDING_API_KEY || !env.RERANK_API_KEY) throw new Error('Missing remote model credentials');
const child = spawn('/root/reponerve-baselines/worker/.pilot-state/baselines/cocoindex-venv/bin/python',
  [resolve(projectRoot, 'scripts/text-fallback/validate.py')],
  { env: { ...process.env, OPENBLAS_NUM_THREADS: '2', OMP_NUM_THREADS: '2' }, stdio: ['pipe', 'inherit', 'inherit'] });
child.stdin.end(JSON.stringify({ embeddingUrl: 'http://127.0.0.1:42002/v1', embeddingKey: env.EMBEDDING_API_KEY,
  reranker: { baseUrl: 'http://127.0.0.1:23504/v1', model: 'Qwen3-Reranker-4B', apiKey: env.RERANK_API_KEY } }) + '\n');
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => { process.exitCode = code ?? 1; });

// Bounded, uncached transport for public-source baseline experiments.
// It never loads questions, reference answers, or corpus files itself.
import { createServer } from 'node:http';
import { readFileSync, writeFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { resolve } from 'node:path';
import { projectRoot } from '../../src/pilot/config.mjs';
import { embeddingTransportConfig } from '../../src/eval/remote-models.mjs';
import { requestEmbeddingBatch } from '../../src/eval/embedding-transport.mjs';

const local = parseEnv(readFileSync(resolve(projectRoot, '.env'), 'utf8'));
const env = { ...local, ...process.env };
const transport = embeddingTransportConfig(env);
const base = transport.baseUrl;
const model = env.EMBEDDING_MODEL ?? 'Qwen3-Embedding-4B';
const key = env.EMBEDDING_API_KEY;
if (!key) throw new Error('EMBEDDING_API_KEY is not configured');
const url = new URL(base);
if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) throw new Error('Invalid embedding endpoint');
const output = resolve(process.argv[2] ?? resolve(projectRoot, '.pilot-state/baselines/gateway.json'));
const stats = { model, dimensions: 1024, requests: 0, items: 0, cacheHits: 0, inputChars: 0, failures: 0, upstreamMs: 0, retries: [], maxAttemptsPerBatch: 3, attemptTimeoutMs: 30000, startedAt: new Date().toISOString() };
let fatal = false;
stats.transport = transport;
stats.maxRequests = 6000;
stats.maxInputChars = 60_000_000;
let chain = Promise.resolve();

async function encode(texts) {
  const vectors = new Array(texts.length);
  const missing = texts.map((text, index) => ({ index, text }));
  for (let start = 0; start < missing.length; start += 8) {
    const batch = missing.slice(start, start + 8);
    const requestStarted = Date.now();
    stats.lastRequest = { items: batch.length, inputChars: batch.reduce((n, x) => n + x.text.length, 0), startedAt: new Date(requestStarted).toISOString() };
    const data = await requestEmbeddingBatch({ url: `${transport.requestBaseUrl.replace(/\/$/, '')}/embeddings`, key, model, texts: batch.map(x => x.text),
      onAttempt: attempt => {
        if (fatal || stats.requests >= stats.maxRequests || stats.inputChars + stats.lastRequest.inputChars > stats.maxInputChars) throw new Error('Gateway execution limit reached');
        stats.requests++; stats.items += batch.length; stats.inputChars += stats.lastRequest.inputChars;
        stats.lastRequest.attempt = attempt;
        writeFileSync(output, JSON.stringify(stats, null, 2)+'\n');
      },
      onRetry: retry => { stats.retries.push({ ...retry, at: new Date().toISOString() }); writeFileSync(output, JSON.stringify(stats, null, 2)+'\n'); },
    });
    stats.lastRequest.elapsedMs = Date.now() - requestStarted;
    stats.upstreamMs += stats.lastRequest.elapsedMs;
    if (!Array.isArray(data.data) || data.data.length !== batch.length) throw new Error('Invalid embedding count');
    const indices = new Set();
    for (const row of data.data) {
      if (!Number.isSafeInteger(row.index) || row.index < 0 || row.index >= batch.length || indices.has(row.index) || !Array.isArray(row.embedding) || row.embedding.length !== 1024 || !row.embedding.every(Number.isFinite)) throw new Error('Invalid embedding response');
      indices.add(row.index);
      const norm = Math.sqrt(row.embedding.reduce((s, v) => s + v*v, 0));
      if (norm < 0.99 || norm > 1.01) throw new Error('Embedding is not normalized');
      const item = batch[row.index]; vectors[item.index] = row.embedding;
      // Deliberately disable embedding cache for measured comparison queries.
    }
    writeFileSync(output, JSON.stringify(stats, null, 2)+'\n');
    if (stats.requests % 25 === 0) console.log(JSON.stringify(stats));
  }
  return { object: 'list', model, data: vectors.map((embedding, index) => ({ object: 'embedding', index, embedding })) };
}

const server = createServer(async (request, response) => {
  const send = (status, data) => { response.writeHead(status, {'content-type':'application/json'}); response.end(JSON.stringify(data)); };
  if (request.url === '/healthz' && request.method === 'GET') return send(200, { ...stats, fatal });
  if (request.url !== '/v1/embeddings' || request.method !== 'POST') return send(404, { error: 'Not found' });
  try {
    let body = ''; for await (const chunk of request) { body += chunk; if (body.length > 4_000_000) throw new Error('Request too large'); }
    const input = JSON.parse(body);
    const texts = typeof input.input === 'string' ? [input.input] : input.input;
    if (!Array.isArray(texts) || !texts.length || texts.length > 2048 || !texts.every(x => typeof x === 'string' && x.length <= 100_000)) throw new Error('Invalid embedding input');
    const task = chain.then(() => encode(texts)); chain = task.catch(() => {});
    send(200, await task);
  } catch (error) {
    stats.firstFailure ??= { name: error.name, message: String(error.message).split(key).join('[REDACTED]').slice(0, 500), code: error.cause?.code, at: new Date().toISOString() };
    fatal = true; stats.failures++; writeFileSync(output, JSON.stringify(stats, null, 2)+'\n');
    send(503, { error: 'Embedding transport failed; run stopped rather than changing providers' });
  }
});
server.listen(0, '127.0.0.1', () => {
  stats.port = server.address().port;
  writeFileSync(output, JSON.stringify(stats, null, 2)+'\n');
  console.log(JSON.stringify({ listening: `http://127.0.0.1:${server.address().port}/v1`, model }));
});
setTimeout(() => { fatal = true; server.closeAllConnections(); server.close(); }, 6000000);

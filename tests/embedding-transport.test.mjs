import test from 'node:test';
import assert from 'node:assert/strict';
import { requestEmbeddingBatch } from '../src/eval/embedding-transport.mjs';

const base = { url: 'https://models.example.com/v1/embeddings', key: 'test-key', model: 'test-model', texts: ['public code'], sleep: async () => {} };
test('Transient embedding failures retry identical inputs and retain attempt accounting', async () => {
  const requests = [], retries = [], attempts = [];
  const data = await requestEmbeddingBatch({ ...base, onAttempt: n => attempts.push(n), onRetry: e => retries.push(e), fetchImpl: async (_, options) => {
    requests.push(options.body);
    return requests.length === 1 ? new Response('{}', { status: 503 }) : Response.json({ data: [1] });
  } });
  assert.deepEqual(data, { data: [1] }); assert.deepEqual(attempts, [1, 2]);
  assert.equal(requests[0], requests[1]); assert.equal(retries.length, 1);
});
test('Embedding retry count is bounded, and authentication or malformed responses fail immediately', async () => {
  let calls = 0;
  await assert.rejects(requestEmbeddingBatch({ ...base, fetchImpl: async () => { calls++; return new Response('{}', { status: 429 }); } }), /HTTP 429/);
  assert.equal(calls, 3);
  for (const status of [400, 401, 403]) {
    calls = 0;
    await assert.rejects(requestEmbeddingBatch({ ...base, fetchImpl: async () => { calls++; return new Response('{}', { status }); } }), new RegExp(`HTTP ${status}`));
    assert.equal(calls, 1);
  }
  calls = 0;
  await assert.rejects(requestEmbeddingBatch({ ...base, fetchImpl: async () => { calls++; return new Response('broken-json'); } }));
  assert.equal(calls, 1);
});

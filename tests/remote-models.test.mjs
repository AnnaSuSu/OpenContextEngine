import test from 'node:test';
import assert from 'node:assert/strict';
import { remoteModelUrl, remoteRerankerConfig, embeddingTransportConfig, rerankerExecutionTransport } from '../src/eval/remote-models.mjs';

test('Rerank defaults to the ordinary API with bounded provider settings', () => {
  const env = {RERANK_BASE_URL:'https://models.example/v2/',RERANK_MODEL:'test',RERANK_API_KEY:'test-only'};
  const config = remoteRerankerConfig(env);
  assert.equal(config.api,'rerank');
  assert.equal(config.baseUrl,'https://models.example/v2');
  assert.equal(config.concurrency,2);
  assert.equal(config.maxDocuments,128);
  assert.equal(remoteRerankerConfig({...env,OCE_RERANK_API:'rerank-batch'}).api,'rerank-batch');
  for (const override of [{OCE_RERANK_API:'auto'}, {OCE_RERANK_CONCURRENCY:'0'},
    {OCE_RERANK_CONCURRENCY:'9'}, {OCE_RERANK_MAX_DOCUMENTS:'1.5'}, {OCE_RERANK_MAX_DOCUMENTS:''}]) {
    assert.throws(() => remoteRerankerConfig({...env,...override}));
  }
});

test('Model configuration refuses localhost, loopback variants, local hostnames and missing remote configuration', () => {
  for (const url of ['http://localhost:8000/v1', 'https://localhost/v1', 'https://127.1/v1', 'https://[::1]/v1', 'https://mac.local/v1', 'https://0.0.0.0/v1']) {
    assert.throws(() => remoteModelUrl(url), /local model inference is prohibited/);
  }
  assert.throws(() => remoteRerankerConfig({}), /No local model will be installed or started/);
  assert.equal(remoteModelUrl('https://models.example.com/v1/'), 'https://models.example.com/v1');
});

test('Same-host remote GPU transport requires a named Linux worker and retains the public provider identity', () => {
  const env = { RERANK_BASE_URL: 'https://models.example.com/v1', RERANK_REMOTE_RUNTIME_URL: 'http://127.0.0.1:23504/v1', RERANK_REMOTE_HOST: 'authorized-worker' };
  const linux = { platform: 'linux', hostname: 'authorized-worker' };
  const result = rerankerExecutionTransport(env, linux);
  assert.equal(result.baseUrl, env.RERANK_BASE_URL);
  assert.equal(result.requestBaseUrl, env.RERANK_REMOTE_RUNTIME_URL);
  assert.throws(() => rerankerExecutionTransport(env, { platform: 'darwin', hostname: 'authorized-worker' }));
  assert.throws(() => rerankerExecutionTransport(env, { platform: 'linux', hostname: 'other-worker' }));
  for (const url of ['http://public.example.com:23504/v1', 'http://127.0.0.1:23504/v1?secret=x', 'http://127.0.0.1/v1']) {
    assert.throws(() => rerankerExecutionTransport({ ...env, RERANK_REMOTE_RUNTIME_URL: url }, linux));
  }
});

test('SSH transport requires an explicit loopback forward while retaining remote provider identity', () => {
  const env = { EMBEDDING_BASE_URL: 'https://models.example.com/v1',
    EMBEDDING_SSH_TUNNEL_URL: 'http://127.0.0.1:42002/v1', EMBEDDING_SSH_REMOTE: 'root@models.example.com:40009' };
  const config = embeddingTransportConfig(env);
  assert.equal(config.baseUrl, env.EMBEDDING_BASE_URL);
  assert.equal(config.requestBaseUrl, env.EMBEDDING_SSH_TUNNEL_URL);
  assert.equal(config.transport, 'ssh-tunnel');
  for (const url of ['http://public.example.com:42002/v1', 'http://127.0.0.1/v1',
    'http://user:password@127.0.0.1:42002/v1', 'http://127.0.0.1:42002/v1?key=secret']) {
    assert.throws(() => embeddingTransportConfig({ ...env, EMBEDDING_SSH_TUNNEL_URL: url }));
  }
  assert.throws(() => embeddingTransportConfig({ ...env, EMBEDDING_SSH_REMOTE: '' }));
  assert.throws(() => embeddingTransportConfig({ ...env, EMBEDDING_BASE_URL: 'http://localhost:8000/v1' }));
  assert.equal(embeddingTransportConfig({ EMBEDDING_BASE_URL: env.EMBEDDING_BASE_URL }).transport, 'https');
});

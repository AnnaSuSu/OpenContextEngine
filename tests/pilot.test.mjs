import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { parseSSE, responseRequest, probe } from '../src/pilot/responses.mjs';
import { loadConfig, publicConfig, redact } from '../src/pilot/config.mjs';
import { scoreEvidence } from '../src/pilot/score.mjs';
import { runCodex } from '../src/pilot/codex.mjs';

test('SSE survives split UTF-8, CRLF, comments, and final partial frame', async () => {
  const bytes = Buffer.from(': ping\r\ndata: {"text":"中文"}\r\n\r\ndata: [DONE]');
  async function* chunks() { for (const b of bytes) yield Uint8Array.of(b); }
  const frames = [];
  for await (const frame of parseSSE(chunks())) frames.push(frame);
  assert.deepEqual(frames, ['{"text":"中文"}', '[DONE]']);
});

const config = { baseUrl: 'https://example.invalid/v1', apiKey: 'test-secret-value',
  model: 'gpt-6.1-sol', effort: 'medium', timeoutMs: 1000, userAgent: 'test' };
test('HTTP 200 without response.completed is a failure', async () => {
  await assert.rejects(responseRequest(config, {}, async () => new Response(
    'data: {"type":"response.created"}\n\ndata: [DONE]\n\n',
    { headers: { 'content-type': 'text/event-stream' } })), /without a successful/);
});
test('Incomplete response never counts as success', async () => {
  await assert.rejects(responseRequest(config, {}, async () => new Response(
    'data: {"type":"response.incomplete","response":{"incomplete_details":{"reason":"max_output_tokens"}}}\n\n',
    { headers: { 'content-type': 'text/event-stream' } })), /max_output_tokens/);
});
test('Redirects fail closed and requested effort/model reach payload', async () => {
  await responseRequest(config, {}, async (url, options) => {
    assert.equal(url, 'https://example.invalid/v1/responses');
    assert.equal(options.redirect, 'error');
    assert.equal(JSON.parse(options.body).reasoning.effort, 'medium');
    return new Response('data: {"type":"response.completed","response":{"status":"completed"}}\n\n',
      { headers: { 'content-type': 'text/event-stream' } });
  });
});
test('Probe forwards the exact tool call id and rejects an invented token', async () => {
  let n = 0;
  const result = await probe(config, 'private-nonce', async (_, payload) => {
    n++;
    if (n === 1) return { response: { output: [{ type: 'function_call', name: 'read_probe_token', call_id: 'call-1' }] } };
    assert.deepEqual(payload.input.at(-1), { type: 'function_call_output', call_id: 'call-1', output: 'private-nonce' });
    return { response: { output: [{ type: 'message', content: [{ type: 'output_text', text: 'wrong' }] }] } };
  });
  assert.equal(result.passed, false);
});
test('Configuration preserves environment priority and redacts secrets', () => {
  const c = loadConfig({ GPT_BASE_URL: 'https://provider.example.com/v1', GPT_API_KEY: 'test-secret-value', GPT_REASONING_EFFORT: 'high' }, '/nonexistent/.env');
  assert.equal(c.effort, 'high');
  assert.equal(c.baseUrl, 'https://provider.example.com/v1');
  assert.throws(() => loadConfig({ GPT_API_KEY: 'x' }, '/nonexistent/.env'), /Set GPT_BASE_URL/);
  assert.equal('apiKey' in publicConfig(c), false);
  assert.ok(!redact('error test-secret-value', [c.apiKey]).includes(c.apiKey));
  assert.throws(() => loadConfig({ GPT_BASE_URL: 'https://provider.example.com/v1', GPT_API_KEY: 'x', GPT_MODEL: 'gpt-6-astra' }, '/nonexistent/.env'), /frozen/);
});
test('Evidence scoring rejects fabricated quotes and escaping paths', async () => {
  const root = await mkdtemp(join(tmpdir(), 'reponerve-score-'));
  try {
    await writeFile(join(root, 'code.py'), 'setup()\ncleanup()\n');
    const task = { units: [{ id: 'cleanup', path: 'code.py', anchors: ['cleanup()'] }] };
    const good = { answer: 'cleanup', evidence: [{ path: 'code.py', start_line: 2, end_line: 2, quote: 'cleanup()' }] };
    assert.equal((await scoreEvidence(JSON.stringify(good), task, root)).coverage, 1);
    good.evidence[0].quote = 'imagined_cleanup()';
    const wrong = await scoreEvidence(JSON.stringify(good), task, root);
    assert.equal(wrong.coverage, 0);
    assert.equal(wrong.invalidEvidence, 1);
    good.evidence[0].path = '../outside';
    assert.equal((await scoreEvidence(JSON.stringify(good), task, root)).invalidEvidence, 1);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('Malformed provider output is a recorded score failure, not a harness crash', async () => {
  const task = { units: [{ id: 'x', path: 'code.py', anchors: ['x'] }] };
  assert.equal((await scoreEvidence('null', task, '/nonexistent')).coverage, 0);
  const result = await scoreEvidence('{"answer":"x","evidence":[null]}', task, '/nonexistent');
  assert.equal(result.invalidEvidence, 1);
  assert.equal(result.coverage, 0);
});

test('Diagnostic execution cannot disable limits or exceed the ten-minute ceiling', async () => {
  for (const override of [{ wallTimeoutMs: null }, { wallTimeoutMs: 600001 }, { maxCommands: null }, { maxCommands: 65 }]) {
    await assert.rejects(runCodex(config, { workspace: '/nonexistent', prompt: '', ...override }), /at most 10 minutes/);
  }
});

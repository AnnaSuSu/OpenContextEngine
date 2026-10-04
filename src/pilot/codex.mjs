import { Codex } from '@openai/codex-sdk';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { redact } from './config.mjs';

export const sdkVersion = '0.160.0';
export const answerSchema = {
  type: 'object', additionalProperties: false, required: ['answer', 'evidence'],
  properties: {
    answer: { type: 'string' },
    evidence: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['path', 'start_line', 'end_line', 'quote'], properties: {
        path: { type: 'string' }, start_line: { type: 'integer' },
        end_line: { type: 'integer' }, quote: { type: 'string' },
      } } },
  },
};

/** A fresh SDK thread, empty Codex home and bounded read-only run per case. */
export async function runCodex(config, { workspace, prompt, effort = config.effort, outputSchema = answerSchema,
  onEvent = () => {}, maxCommands = 24, wallTimeoutMs = config.timeoutMs,
  streamIdleTimeoutMs = config.timeoutMs }) {
  if (!Number.isInteger(wallTimeoutMs) || wallTimeoutMs <= 0 || wallTimeoutMs > 600000 ||
      !Number.isInteger(maxCommands) || maxCommands <= 0 || maxCommands > 64) {
    throw new Error('Run must have positive limits: at most 10 minutes and 64 commands');
  }
  const isolatedHome = await mkdtemp(join(tmpdir(), 'opencontextengine-codex-'));
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error('Pilot wall-clock budget exceeded')), wallTimeoutMs);
  const started = performance.now();
  const result = { sdkVersion, runtimeVersion: '0.160.0', effort, completed: false,
    maxCommands, timeoutMs: wallTimeoutMs, streamIdleTimeoutMs,
    commandCount: 0, successfulCommands: 0, commandOutputChars: 0, usage: null,
    finalResponse: '', errors: [] };
  try {
    await mkdir(join(isolatedHome, 'tmp'), { recursive: true });
    // The only key passed to Codex is the explicitly selected provider key.
    // Tool subprocesses receive a separate minimal environment without it.
    const env = { PATH: process.env.PATH || '/usr/bin:/bin', HOME: process.env.HOME,
      TMPDIR: join(isolatedHome, 'tmp'), CODEX_HOME: isolatedHome, GPT_API_KEY: config.apiKey };
    const codex = new Codex({ env, config: {
      model_provider: 'configured_provider', project_doc_max_bytes: 0,
      model_providers: { configured_provider: { name: 'OpenContextEngine relay', base_url: config.baseUrl,
        env_key: 'GPT_API_KEY', wire_api: 'responses', requires_openai_auth: false,
        request_max_retries: 0, stream_max_retries: 0, stream_idle_timeout_ms: streamIdleTimeoutMs,
        http_headers: { 'User-Agent': config.userAgent } } },
      shell_environment_policy: { inherit: 'none', set: { PATH: '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin' } },
      features: { multi_agent: false, shell_snapshot: false },
    } });
    const thread = codex.startThread({ model: config.model, modelReasoningEffort: effort,
      workingDirectory: workspace, skipGitRepoCheck: true, sandboxMode: 'read-only',
      approvalPolicy: 'never', networkAccessEnabled: false, webSearchMode: 'disabled' });
    const { events } = await thread.runStreamed(prompt, { outputSchema, signal: controller.signal });
    for await (const event of events) {
      // Persist only SDK events, never transport headers or process environment.
      await onEvent(JSON.parse(redact(event, [config.apiKey])));
      if (event.type === 'item.started' && event.item.type === 'command_execution') {
        result.commandCount++;
        if (result.commandCount > maxCommands) {
          controller.abort(new Error('Pilot command budget exceeded'));
          throw new Error('Pilot command budget exceeded');
        }
      }
      if (event.type === 'item.completed') {
        if (event.item.type === 'command_execution') {
          result.commandOutputChars += event.item.aggregated_output.length;
          if (event.item.exit_code === 0) result.successfulCommands++;
        }
        if (event.item.type === 'agent_message') result.finalResponse = event.item.text;
      }
      if (event.type === 'turn.completed') { result.completed = true; result.usage = event.usage; }
      if (event.type === 'turn.failed') result.errors.push(event.error.message);
      if (event.type === 'error') result.errors.push(event.message);
    }
    if (!result.completed) result.errors.push('No turn.completed event');
  } catch (error) {
    result.completed = false;
    result.errors.push(controller.signal.aborted ? String(controller.signal.reason?.message || 'Aborted') : error.message);
  } finally {
    clearTimeout(timer);
    result.elapsedMs = Math.round(performance.now() - started);
    // This directory was created by this function; it holds no user's sessions.
    await rm(isolatedHome, { recursive: true, force: true });
  }
  return JSON.parse(redact(result, [config.apiKey]));
}

export async function sdkSmoke(config) {
  const workspace = await mkdtemp(join(tmpdir(), 'opencontextengine-smoke-'));
  const token = crypto.randomUUID();
  try {
    await mkdir(join(workspace, 'settings'));
    await writeFile(join(workspace, 'settings', 'runtime.ini'), `probe_token=${token}\n`);
    const result = await runCodex(config, { workspace,
      prompt: 'This is a read-only integration check. Search files in the current directory using a shell tool, then read the matching file using another shell tool call. Find the value of probe_token. Do not inspect any path outside this directory, run network commands, or read environment variables. Set login=false on shell calls when available. Return the exact value as answer plus the source line as evidence. Do not guess the value.' });
    let parsed;
    try { parsed = JSON.parse(result.finalResponse); } catch { /* failure recorded below */ }
    return { ...result, passed: result.completed && result.successfulCommands >= 2 && parsed?.answer === token,
      tokenRoundTrip: parsed?.answer === token };
  } finally { await rm(workspace, { recursive: true, force: true }); }
}

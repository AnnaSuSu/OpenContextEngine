import { readFileSync, existsSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

export const projectRoot = fileURLToPath(new URL('../../', import.meta.url));

export function loadConfig(environment = process.env, envFile = resolve(projectRoot, '.env')) {
  const local = existsSync(envFile) ? parseEnv(readFileSync(envFile, 'utf8')) : {};
  const env = { ...local, ...environment };
  const baseUrl = (env.GPT_BASE_URL || 'https://provider.example.com/v1').replace(/\/+$/, '');
  const url = new URL(baseUrl);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('GPT_BASE_URL must be an HTTPS URL without credentials, query or fragment');
  }
  const model = env.GPT_MODEL || 'gpt-6.1-sol';
  if (model !== 'gpt-6.1-sol') throw new Error('This pilot is frozen to gpt-6.1-sol');
  const effort = env.GPT_REASONING_EFFORT || 'medium';
  if (!['low', 'medium', 'high', 'xhigh', 'max'].includes(effort)) throw new Error('Unsupported reasoning effort');
  const timeoutMs = Number(env.GPT_TIMEOUT_MS || 300000);
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 600000) {
    throw new Error('GPT_TIMEOUT_MS must be an integer between 1000 and 600000');
  }
  if (!env.GPT_API_KEY?.trim()) throw new Error('Set GPT_API_KEY in the environment or project .env');
  return { baseUrl, model, effort, timeoutMs, apiKey: env.GPT_API_KEY.trim(),
    userAgent: env.GPT_USER_AGENT || 'OpenContextEngine-Pilot/0.1' };
}

export function publicConfig({ apiKey, ...config }) { return config; }

export function redact(value, secrets = []) {
  let text = typeof value === 'string' ? value : JSON.stringify(value);
  for (const secret of secrets.filter(Boolean)) text = text.split(secret).join('[REDACTED]');
  return text.replace(/Bearer\s+[^\s"\\]+/gi, 'Bearer [REDACTED]')
    .replace(/sk-[A-Za-z0-9_-]{12,}/g, '[REDACTED]');
}

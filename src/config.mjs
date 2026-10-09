import { existsSync, readFileSync, mkdirSync, writeFileSync, renameSync, rmSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';
import { randomUUID } from 'node:crypto';
import { normalizeEnvironment } from './environment.mjs';

export const projectRoot = fileURLToPath(new URL('../', import.meta.url));
export const configKeys = new Set([
  'EMBEDDING_BASE_URL','EMBEDDING_API_KEY','EMBEDDING_MODEL','EMBEDDING_SSH_TUNNEL_URL','EMBEDDING_SSH_REMOTE',
  'RERANK_BASE_URL','RERANK_API_KEY','RERANK_MODEL','RERANK_REMOTE_RUNTIME_URL','RERANK_REMOTE_HOST',
  'RERANK_SSH_TUNNEL_URL','RERANK_SSH_REMOTE',
  'OCE_ALLOW_HTTP','OCE_RERANK_API','OCE_RERANK_CONCURRENCY','OCE_RERANK_MAX_DOCUMENTS','OCE_EMBEDDING_DIMENSIONS',
  'OCE_EMBEDDING_REVISION','OCE_EMBEDDING_BATCH_SIZE','OCE_EMBEDDING_CONCURRENCY','OCE_PYTHON','OCE_GO_BINARY','OCE_LANGUAGE_OPTIONS','OCE_POLL_SECONDS',
  'OCE_DEBOUNCE_SECONDS','OCE_SCAN_IDLE_SECONDS','OCE_UNLOAD_IDLE_SECONDS','OCE_MAX_RESIDENT_WORKERS','OCE_MAX_CONCURRENT_BUILDS','OCE_RESOURCE_DIRECTORY','OCE_MAX_WORKSPACES','OCE_WORKSPACE_IDLE_SECONDS','OCE_API_KEY','OCE_BASE_URL','TIKTOKEN_CACHE_DIR',
]);
export function configDirectory(environment = process.env) {
  return resolve(environment.OCE_CONFIG_HOME || join(homedir(), '.config', 'opencontextengine'));
}
export function readUserConfig(environment = process.env) {
  const path = join(configDirectory(environment), 'config.json');
  if (!existsSync(path)) return {};
  let data;
  try {data = JSON.parse(readFileSync(path, 'utf8'));} catch {throw new Error(`Invalid OpenContextEngine configuration: ${path}`);}
  if (data?.schemaVersion !== 1 || !data.env || typeof data.env !== 'object' || Array.isArray(data.env)
      || Object.entries(data.env).some(([key,value]) => !configKeys.has(key) || typeof value !== 'string')) {
    throw new Error(`Invalid OpenContextEngine configuration: ${path}`);
  }
  return data.env;
}
export function loadEnvironment(environment = process.env, checkout = projectRoot) {
  const file = join(checkout, '.env');
  return {...normalizeEnvironment(existsSync(file) ? parseEnv(readFileSync(file,'utf8')) : {}),
    ...readUserConfig(environment),
    ...normalizeEnvironment(environment)};
}
export function saveUserConfig(values, environment = process.env) {
  const directory = configDirectory(environment), path = join(directory,'config.json');
  const env = Object.fromEntries(Object.entries(values).filter(([key]) => configKeys.has(key)));
  if (Object.values(env).some(value => typeof value !== 'string')) throw new Error('Configuration values must be strings');
  mkdirSync(directory, {recursive:true,mode:0o700});
  const temporary = join(directory, `.config-${randomUUID()}.tmp`);
  try {
    writeFileSync(temporary, JSON.stringify({schemaVersion:1,env},null,2)+'\n', {flag:'wx',mode:0o600});
    renameSync(temporary,path);
  } finally {rmSync(temporary,{force:true});}
  return path;
}

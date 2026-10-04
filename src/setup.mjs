import { createInterface } from 'node:readline/promises';
import { Writable } from 'node:stream';
import { configDirectory, loadEnvironment, saveUserConfig } from './config.mjs';
import { remoteRerankerConfig, embeddingTransportConfig } from './eval/remote-models.mjs';
import { ensureRuntime, run } from './runtime.mjs';

export function validateModels(env) {
  embeddingTransportConfig(env);
  remoteRerankerConfig(env);
  for (const key of ['EMBEDDING_API_KEY','EMBEDDING_MODEL']) {
    if (!env[key]?.trim()) throw new Error(`Set ${key}`);
  }
  const dimensions = Number(env.OCE_EMBEDDING_DIMENSIONS);
  if (!Number.isInteger(dimensions) || dimensions < 1) throw new Error('Embedding dimensions must be a positive integer');
}

export function terminalPrompt(input = process.stdin, output = process.stderr) {
  if (!input.isTTY || !output.isTTY) throw new Error('Run setup in a terminal, or use --non-interactive with model environment variables');
  let muted = false;
  const sink = new Writable({write(chunk,encoding,callback) {if (!muted) output.write(chunk,encoding); callback();}});
  sink.isTTY = true; sink.columns = output.columns;
  const terminal = createInterface({input,output:sink,terminal:true});
  const abort = new AbortController();
  terminal.on('SIGINT',() => abort.abort());
  return {
    async ask(label,current = '',secret = false) {
      const hint = current ? (secret ? ' [saved; Enter to keep]' : ` [${current}]`) : '';
      if (!secret) return (await terminal.question(`${label}${hint}: `,{signal:abort.signal})).trim() || current;
      output.write(`${label}${hint}: `);
      muted = true;
      try {return (await terminal.question('',{signal:abort.signal})).trim() || current;}
      finally {muted = false; output.write('\n');}
    },
    close() {terminal.close();},
  };
}

export async function setup({environment = process.env, nonInteractive = false, python,
  prompt, install = ensureRuntime, execute = run, log = message => process.stderr.write(message+'\n')} = {}) {
  if (!['darwin','linux'].includes(process.platform)) throw new Error('OpenContextEngine currently supports macOS and Linux');
  let env = {EMBEDDING_MODEL:'Qwen3-Embedding-4B',RERANK_MODEL:'Qwen3-Reranker-4B',
    OCE_EMBEDDING_DIMENSIONS:'1024',...loadEnvironment(environment)};
  log(`Configuration: ${configDirectory(environment)}`);
  if (!nonInteractive) {
    const questions = prompt || terminalPrompt();
    try {
      for (const [key,label,secret] of [
        ['EMBEDDING_BASE_URL','Embedding base URL (including /v1)'],
        ['EMBEDDING_API_KEY','Embedding API key',true],['EMBEDDING_MODEL','Embedding model'],
        ['OCE_EMBEDDING_DIMENSIONS','Embedding dimensions'],
        ['RERANK_BASE_URL','Rerank base URL (before /rerank; include a version prefix if required)'],
        ['RERANK_API_KEY','Rerank API key',true],['RERANK_MODEL','Rerank model'],
      ]) env[key] = await questions.ask(label,env[key] || '',Boolean(secret));
    } finally {questions.close();}
  }
  validateModels(env);
  await execute('git',['--version'],{timeout:10000});
  if (python) delete env.OCE_PYTHON;
  const runtime = await install(env,{python:python || 'python3',execute,log});
  env = {...env,...runtime};
  const path = saveUserConfig(env,environment);
  log(`Saved configuration to ${path}. API keys are stored with owner-only file permissions.`);
  log('Setup complete. Go projects additionally require Go 1.22+ on PATH or OCE_GO_BINARY.');
  return {path,env};
}

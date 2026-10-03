import { readFileSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { DirectContext, resolveAugmentCredentials } from '@augmentcode/auggie-sdk';
import { projectRoot, redact } from '../../src/pilot/config.mjs';
import { sha256, validateAnswers } from '../../src/eval/evidence.mjs';

const repo=process.argv[2];
if(!['click','httpx','zod'].includes(repo)||process.argv.slice(3).some(x=>x!=='--dry-run'))throw Error('Usage: node scripts/expanded/ace.mjs click|httpx|zod [--dry-run]');
const dryRun=process.argv.includes('--dry-run');
const datasetId=`expanded-v1/${repo}`;
const base=resolve(projectRoot,'eval',datasetId);
const read = name => JSON.parse(readFileSync(resolve(base, name), 'utf8'));
const protocol = read('protocol.json');
const queries = read('queries.json');
const snapshot = read('snapshot.json');
const gold = read('answers.v1.json');
const freeze = read('freeze.json');
for (const [name, hash] of Object.entries(freeze.sha256)) {
  if (sha256(readFileSync(resolve(base, name))) !== hash) throw new Error(`Frozen file changed: ${name}`);
}
if (![queries.commit, gold.commit].every(commit => commit === snapshot.commit)) throw new Error('Commit mismatch');
const limits = protocol.limits;
// Non-configurable ceilings keep edits to the protocol from enabling an unbounded run.
if (Object.values(limits).some(value => !Number.isSafeInteger(value) || value <= 0) ||
  limits.totalMs > 600000 || limits.httpRequests > 160 || limits.retrievalRequests > 24 ||
  limits.queries !== 20 || limits.uploadBytes > 7000000 || limits.files > 1000) throw new Error('Unsafe run limits');
if (JSON.parse(readFileSync(resolve(projectRoot, 'node_modules/@augmentcode/auggie-sdk/package.json'), 'utf8')).version !== protocol.ace.sdkVersion) {
  throw new Error('SDK version mismatch');
}
const corpus = realpathSync(resolve(projectRoot, '.pilot-state',datasetId,'corpus'));
const files = snapshot.files.map(file => {
  if (!/^[a-zA-Z0-9_./-]+\.(py|ts|tsx)$/.test(file.path) || file.path.split('/').includes('..')) throw new Error('Invalid corpus path');
  const path = realpathSync(resolve(corpus, file.path));
  if (!path.startsWith(corpus + sep)) throw new Error('Corpus path escapes root');
  const data = readFileSync(path);
  if (data.length !== file.bytes || sha256(data) !== file.sha256 || data.length > limits.singleFileBytes) {
    throw new Error(`Invalid corpus file: ${file.path}`);
  }
  return { path: file.path, contents: data.toString('utf8') };
});
const sourceLines = new Map(files.map(file => [file.path, file.contents.replace(/\r\n/g, '\n').split('\n')]));
validateAnswers(gold.answers, sourceLines);
if (gold.answers.length !== queries.cases.length || queries.cases.some(task => !gold.answers.some(a => a.id === task.id))) {
  throw new Error('Questions and answers do not match');
}
const orderedQueries = queries.cases.flatMap((task, i) => (i % 2 ? ['en', 'zh'] : ['zh', 'en'])
  .map(language => ({ id: task.id, language, query: task.queries[language] })));
if (queries.cases.length !== 10 || new Set(queries.cases.map(t => t.id)).size !== 10 ||
  orderedQueries.some(q => !/^[a-z-]+$/.test(q.id) || typeof q.query !== 'string' || !q.query.trim()) ||
  orderedQueries.length !== limits.queries || files.length > limits.files ||
  files.reduce((sum, file) => sum + Buffer.byteLength(file.contents), 0) > limits.uploadBytes) throw new Error('Scope exceeded');
if (dryRun) {
  console.log(JSON.stringify({ status: 'preflight-passed', files: files.length, queries: orderedQueries.length,
    units: gold.answers.reduce((sum, a) => sum + a.units.length, 0), commit: snapshot.commit }));
  process.exit(0);
}

const start = Date.now();
const directory = resolve(projectRoot, 'runs', `ace-${repo}-expanded-${new Date(start).toISOString().replaceAll(':', '-')}`);
mkdirSync(directory, { recursive: true, mode: 0o700 });
for (const name of [...Object.keys(freeze.sha256), 'freeze.json']) {
  writeFileSync(resolve(directory, name), readFileSync(resolve(base, name)), { mode: 0o600 });
}
const report = { schemaVersion: 1, kind: 'frozen-cross-repository-evaluation', system:'ace', datasetId, startedAt: new Date(start).toISOString(),
  mode: 'DirectContext.search', sdkVersion: protocol.ace.sdkVersion, protocolId: protocol.id,
  commit: snapshot.commit, freeze, status: 'running', stage: 'credentials', requests: [], results: [],
  billing: { tokens: null, cost: null }, corpus: { files: files.length,
    bytes: snapshot.files.reduce((sum, f) => sum + f.bytes, 0) } };
const save = () => writeFileSync(resolve(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
const finish = (status, error) => {
  report.status = status; report.elapsedMs = Date.now() - start;
  if (error) report.error = error;
  save();
};
const stop = reason => { finish('failed', reason); process.exit(1); };
let secrets = [];
let stageTimer;
const totalTimer = setTimeout(() => stop('Total deadline exceeded'), limits.totalMs);
const stage = (name, timeoutMs) => {
  clearTimeout(stageTimer); report.stage = name; save();
  console.log(JSON.stringify({ stage: name, elapsedMs: Date.now() - start }));
  stageTimer = setTimeout(() => stop(`${name} deadline exceeded`), timeoutMs);
};
const heartbeat = setInterval(() => console.log(JSON.stringify({ stage: report.stage,
  elapsedMs: Date.now() - start, requests: report.requests.length, finished: report.results.length })), 30000);
process.once('SIGTERM', () => stop('Terminated'));
process.once('SIGINT', () => stop('Interrupted'));
save();
try {
  const credentials = await resolveAugmentCredentials();
  secrets = [credentials.apiKey, credentials.apiUrl];
  const tenant = new URL(credentials.apiUrl);
  if (tenant.protocol !== 'https:' || !tenant.hostname.endsWith('.augmentcode.com') ||
    tenant.username || tenant.password || tenant.search || tenant.hash) throw new Error('Expected official Augment tenant');
  const originalFetch = globalThis.fetch;
  const allowed = new Set(['find-missing', 'batch-upload', 'checkpoint-blobs', 'agents/codebase-retrieval']);
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url ?? input.href);
    const prefix = credentials.apiUrl.replace(/\/+$/, '') + '/';
    const endpoint = url.href.startsWith(prefix) ? url.href.slice(prefix.length) : '';
    if (url.origin !== tenant.origin || !allowed.has(endpoint) || options.method !== 'POST') throw new Error('Disallowed SDK request');
    if (report.requests.length >= limits.httpRequests || (endpoint === 'agents/codebase-retrieval' &&
      report.requests.filter(r => r.endpoint === endpoint).length >= limits.retrievalRequests)) throw new Error('Request cap reached');
    const item = { number: report.requests.length + 1, endpoint, stage: report.stage,
      startedAt: new Date().toISOString() };
    report.requests.push(item); save();
    const begin = Date.now();
    try {
      const timeout = AbortSignal.timeout(limits.requestMs);
      const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
      const response = await originalFetch(input, { ...options, signal, redirect: 'error' });
      item.status = response.status; item.headersMs = Date.now() - begin; save();
      return response;
    } catch (error) { item.error = redact(error.message, secrets); save(); throw error; }
  };
  stage('indexing', limits.indexingMs);
  const context = await DirectContext.create({ ...credentials, debug: false });
  const indexStart = Date.now();
  const result = await context.addToIndex(files, { timeout: limits.indexingMs });
  report.indexing = { elapsedMs: Date.now() - indexStart, newlyUploaded: result.newlyUploaded.length,
    alreadyUploaded: result.alreadyUploaded.length, indexedPaths: context.getIndexedPaths().length };
  if (report.indexing.indexedPaths !== files.length) throw new Error('Index count mismatch');
  writeFileSync(resolve(directory, 'index-state.json'), JSON.stringify(context.export()) + '\n', { mode: 0o600 });
  for (const task of orderedQueries) {
    stage(`search:${task.id}:${task.language}`, limits.queryMs);
    const begin = Date.now();
    try {
      const raw = await context.search(task.query, { maxOutputLength: protocol.ace.maxOutputLength });
      if (typeof raw !== 'string' || !raw.trim()) throw new Error('Empty search response');
      const rawFile = `${task.id}.${task.language}.txt`;
      writeFileSync(resolve(directory, rawFile), raw, { mode: 0o600 });
      const row = { ...task, status: 'completed', elapsedMs: Date.now() - begin, characters: raw.length,
        rawFile, sha256: sha256(raw), exceedsCharacterLimit: raw.length > protocol.ace.maxOutputLength };
      report.results.push(row); save();
      console.log(JSON.stringify({ id: row.id, language: row.language, elapsedMs: row.elapsedMs, characters: row.characters }));
    } catch (error) {
      report.results.push({ ...task, status: 'failed', elapsedMs: Date.now() - begin, error: redact(error.message, secrets) });
      save(); throw error; // retain the failure and stop further paid queries
    }
  }
  finish('completed');
  console.log(JSON.stringify({ status: report.status, directory, elapsedMs: report.elapsedMs }));
} catch (error) {
  finish('failed', redact(error.message, secrets));
  console.error(JSON.stringify({ status: report.status, error: report.error, directory }));
  process.exitCode = 1;
} finally {
  clearTimeout(totalTimer); clearTimeout(stageTimer); clearInterval(heartbeat);
}

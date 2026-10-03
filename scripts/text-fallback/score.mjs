// Score frozen references locally, after retrieval; never send labels to models.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { projectRoot } from '../../src/pilot/config.mjs';
import { sha256, tokenCount, validateAnswers, scoreEvidence } from '../../src/eval/evidence.mjs';

const base = resolve(projectRoot, 'eval/text-fallback-v1');
const run = resolve(projectRoot, 'runs/text-fallback-v1');
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const frozen = read(resolve(base, 'freeze.json'));
for (const [name, hash] of Object.entries(frozen.sha256)) {
  if (sha256(readFileSync(resolve(base, name))) !== hash) throw new Error('Changed frozen input: ' + name);
}
const report = read(resolve(run, 'report.json'));
const code = read(resolve(base, 'engine-freeze.json'));
if (JSON.stringify(report.code) !== JSON.stringify(code) || JSON.stringify(report.freeze) !== JSON.stringify(frozen)) {
  throw new Error('Run identity mismatch');
}
for (const [name, hash] of Object.entries(code.sha256)) {
  if (sha256(readFileSync(resolve(projectRoot, name))) !== hash) throw new Error('Changed evaluated implementation: ' + name);
}
const snapshot = read(resolve(base, 'snapshot.json'));
const sources = new Map(snapshot.files.map(file => {
  const raw = readFileSync(resolve(projectRoot, '.pilot-state/text-fallback-v1/corpus', file.path));
  if (sha256(raw) !== file.sha256) throw new Error('Changed source: ' + file.path);
  return [file.path, raw.toString('utf8').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').split('\n')];
}));
const answers = read(resolve(base, 'answers.v1.json')).answers;
validateAnswers(answers, sources);
const queries = read(resolve(base, 'queries.json')).cases;
if (report.results.length !== queries.length * 2) throw new Error('Incomplete run');
const rows = [];
for (const task of queries) for (const language of ['zh', 'en']) {
  const matches = report.results.filter(row => row.id === task.id && row.language === language);
  if (matches.length !== 1) throw new Error('Missing or duplicate result');
  const result = matches[0];
  let raw = '';
  if (result.status === 'completed') {
    if (result.rawFile !== `${task.id}.${language}.txt` || result.nativeFile !== `${task.id}.${language}.json`) throw new Error('Unexpected result path');
    raw = readFileSync(resolve(run, result.rawFile), 'utf8');
    if (sha256(raw) !== result.sha256) throw new Error('Changed raw result');
    const debug = read(resolve(run, result.nativeFile));
    if (debug.tokens !== tokenCount(raw) || debug.tokens > 4000 || debug.rerankedCount > 80 ||
        debug.modelRequests.embedding !== 1 || debug.modelRequests.rerank > 2 || debug.queryCache !== false) {
      throw new Error('Retrieval budget or model-call limit violated');
    }
  }
  const score = scoreEvidence(raw, answers.find(a => a.id === task.id), sources);
  if (score.diagnostic.invalid.length) throw new Error('Invalid source line in result');
  rows.push({ ...result, tokens: tokenCount(raw), score });
}
const latency = rows.filter(row => row.status === 'completed').map(row => row.elapsedMs).sort((a, b) => a - b);
const summary = {
  queries: rows.length, completed: latency.length,
  coverage: rows.reduce((sum, row) => sum + row.score.coverage, 0) / rows.length,
  completeCount: rows.filter(row => row.score.complete).length,
  medianMs: latency.length ? (latency[Math.floor((latency.length - 1) / 2)] + latency[Math.floor(latency.length / 2)]) / 2 : null,
  p95Ms: latency.length ? latency[Math.ceil(latency.length * .95) - 1] : null,
};
const output = { kind: 'source-derived mixed-language smoke; not ACE comparison or held-out benchmark',
  repository: snapshot.repository, commit: snapshot.commit, independentTasks: queries.length,
  budget: 4000, timing: 'Remote worker internal time; excludes indexing; not previous Mac client latency',
  index: report.index, indexEmbeddingRequests: report.indexEmbeddingRequests,
  summary, rows, validation: { frozenInputs: true, evaluatedSourceHashes: true,
    rawHashes: true, sourceLines: true, modelBudget: true, referenceAnswersKeptLocal: true } };
const path = resolve(projectRoot, 'docs/eval/results/text-fallback-smoke-20261004.json');
writeFileSync(path, JSON.stringify(output, null, 2) + '\n');
console.log(JSON.stringify({ output: path, summary }));

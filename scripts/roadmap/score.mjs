// Local-only scoring: source and response hashes, exact lines, token/model limits.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { sha256, tokenCount, validateAnswers, scoreEvidence } from '../../src/eval/evidence.mjs';

const directory = resolve(process.argv[2]);
const read = p => JSON.parse(readFileSync(p, 'utf8'));
const report = read(resolve(directory, 'report.json'));
const datasets = {};
for (const name of Object.keys(report.indexes)) {
  const base = name === 'esbuild' ? 'eval/text-fallback-v1'
    : ['cobra', 'commander'].includes(name) ? `eval/js-go-v1/${name}` : `eval/expanded-v1/${name}`;
  const corpus = name === 'esbuild' ? '.pilot-state/text-fallback-v1/corpus'
    : ['cobra', 'commander'].includes(name) ? `.pilot-state/roadmap-v1/${name}` : `.pilot-state/expanded-v1/${name}/corpus`;
  const frozen = read(`${base}/freeze.json`);
  for (const [file, hash] of Object.entries(frozen.sha256)) {
    if (sha256(readFileSync(`${base}/${file}`)) !== hash) throw Error('Changed frozen input');
  }
  const sources = new Map(read(`${base}/snapshot.json`).files.map(file => {
    const raw = readFileSync(`${corpus}/${file.path}`);
    if (sha256(raw) !== file.sha256) throw Error('Changed source');
    return [file.path, raw.toString('utf8').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').split('\n')];
  }));
  const answers = read(`${base}/answers.v1.json`).answers;
  validateAnswers(answers, sources);
  datasets[name] = { sources, answers, queries: read(`${base}/queries.json`).cases };
  if (report.indexes[name].queriesSha256 && report.indexes[name].queriesSha256 !== sha256(readFileSync(`${base}/queries.json`))) throw Error('Run queried different questions');
}
const seen = new Set();
const rows = report.results.map(row => {
  const key = `${row.dataset}.${row.id}.${row.language}.${row.variant}`;
  if (seen.has(key) || row.rawFile !== key+'.txt' || row.nativeFile !== key+'.json') throw Error('Duplicate or mismatched result');
  seen.add(key);
  const { sources, answers, queries } = datasets[row.dataset];
  const query = queries.find(q => q.id === row.id)?.queries[row.language];
  const raw = readFileSync(resolve(directory, row.rawFile), 'utf8');
  const debug = read(resolve(directory, row.nativeFile));
  if (!query || query !== debug.plan.intent || sha256(raw) !== row.sha256) throw Error('Changed query or raw result');
  const tokens = tokenCount(raw);
  if (tokens !== debug.tokens || tokens > 4000 || debug.rerankedCount > 80 || debug.queryCache !== false ||
      debug.modelRequests.embedding !== 1 || debug.modelRequests.rerank > 2) throw Error('Retrieval budget violated');
  const score = scoreEvidence(raw, answers.find(a => a.id === row.id), sources);
  if (score.diagnostic.invalid.length) throw Error('Invalid returned source line');
  return { ...row, tokens, score };
});
const summary = {};
for (const dataset of Object.keys(datasets)) {
  summary[dataset] = {};
  for (const variant of [...new Set(rows.filter(r => r.dataset === dataset).map(r => r.variant))]) {
    const group = rows.filter(r => r.dataset === dataset && r.variant === variant);
    if (group.length !== datasets[dataset].queries.length*2) throw Error('Incomplete dataset: '+dataset);
    const times = group.map(r => r.elapsedMs).sort((a, b) => a-b);
    summary[dataset][variant] = { queries: group.length,
      coverage: group.reduce((sum, r) => sum+r.score.coverage, 0)/group.length,
      complete: group.filter(r => r.score.complete).length,
      medianMs: (times[Math.floor((times.length-1)/2)]+times[Math.floor(times.length/2)])/2,
      p95Ms: times[Math.ceil(times.length*.95)-1] };
  }
}
const result = { kind: 'source-derived development evaluation; not independent benchmark',
  runReportSha256: sha256(readFileSync(resolve(directory, 'report.json'))),
  code: report.code, indexes: report.indexes, summary, rows,
  validation: { frozenInputs: true, rawHashes: true, queryIdentity: true, exactSourceLines: true, budgets: true } };
writeFileSync(resolve(directory, 'scores.json'), JSON.stringify(result, null, 2)+'\n');
console.log(JSON.stringify(summary, null, 2));

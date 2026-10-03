// Offline diagnostics only. Reference answers are never passed to retrieval.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { sha256 } from '../src/eval/evidence.mjs';

const directories = process.argv.slice(2).map(path => resolve(path));
if (!directories.length) throw new Error('Usage: node scripts/compare-django.mjs RUN_DIRECTORY...');
const systems = [];
let referenceHash, commit;
for (const directory of directories) {
  const read = name => JSON.parse(readFileSync(resolve(directory, name), 'utf8'));
  const report = read('report.json'), score = read('scores.v2.json'), gold = read('answers.v2.json');
  if (report.status !== 'completed' || report.results.length !== 20 || score.rows.some(row => row.status !== 'completed')) {
    throw new Error(`Only complete 20-query runs can be compared: ${directory}`);
  }
  if (score.answerSha256 !== sha256(readFileSync(resolve(directory, 'answers.v2.json')))) throw new Error('Reference hash mismatch');
  referenceHash ??= score.answerSha256; commit ??= score.commit;
  if (referenceHash !== score.answerSha256 || commit !== score.commit || score.primaryBudget !== 4000) throw new Error('Incomparable runs');
  const tasks = new Map(gold.answers.map(task => [task.id, task]));
  const diagnostics = {};
  for (const language of ['zh', 'en']) {
    const rows = score.rows.filter(row => row.language === language);
    const misses = [];
    for (const row of rows) {
      const primary = row.budgetScores.find(item => item.budget === 4000);
      const task = tasks.get(row.id);
      for (const unit of primary.units.filter(unit => !unit.covered)) {
        const rawUnit = row.rawScore.units.find(item => item.id === unit.id);
        const expected = task.units.find(item => item.id === unit.id);
        const anyRequiredLineReturned = rawUnit.alternatives.some((alternative, i) => {
          const total = expected.alternatives[i].allOf.reduce((n, span) => n + span.endLine - span.startLine + 1, 0);
          const missing = alternative.missing.reduce((n, span) => n + span.missingLines.length, 0);
          return missing < total;
        });
        misses.push({ task: row.id, unit: unit.id, kind: rawUnit.covered ? 'lost-to-budget'
          : anyRequiredLineReturned ? 'incomplete-in-raw-return' : 'absent-from-raw-return' });
      }
    }
    diagnostics[language] = {
      rawCoverage: rows.reduce((n, row) => n + row.rawScore.coverage, 0) / rows.length,
      rawTokens: { min: Math.min(...rows.map(row => row.rawTokens)), max: Math.max(...rows.map(row => row.rawTokens)) },
      missingUnitCounts: Object.fromEntries(['lost-to-budget', 'incomplete-in-raw-return', 'absent-from-raw-return']
        .map(kind => [kind, misses.filter(item => item.kind === kind).length])),
      misses,
    };
  }
  const system = report.system ?? (report.mode === 'DirectContext.search' ? 'ace' : null);
  if (!system) throw new Error('Unknown retrieval system');
  systems.push({ system, run: directory.split('/').at(-1),
    summary: score.summary, diagnostics, config: report.config,
    elapsedMs: report.elapsedMs, indexingMs: report.indexingMs ?? report.indexing?.elapsedMs,
    indexAndFirstQueryMs: report.indexAndFirstQueryMs,
    queryMs: report.results.map(row => ({ id: row.id, language: row.language, elapsedMs: row.elapsedMs })),
    scoreSha256: sha256(readFileSync(resolve(directory, 'scores.v2.json'))) });
}
const result = { schemaVersion: 1, kind: 'development-pilot-comparison', commit, referenceHash,
  primaryBudgetTokens: 4000, independentTasks: 10,
  notes: ['Single run; paired Chinese and English queries are not independent tasks.',
    'Missing-unit categories describe the frozen reference spans, not all possible relevant evidence.',
    'Timing depends on deployment and model configuration; not an isolated algorithm speed comparison.'], systems };
const output = resolve('docs/eval/results/django-comparison-20261003.json');
writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ saved: output, systems: systems.map(s => ({ system: s.system, main: s.summary[4000], diagnostics: s.diagnostics })) }, null, 2));

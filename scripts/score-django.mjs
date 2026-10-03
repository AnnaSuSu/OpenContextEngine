import { readFileSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { projectRoot } from '../src/pilot/config.mjs';
import { sha256, tokenCount, budgetPrefix, validateAnswers, scoreEvidence } from '../src/eval/evidence.mjs';

if (!process.argv[2] || process.argv.length > 4) throw new Error('Usage: npm run score-django -- runs/ace-django-TIMESTAMP [answers.vN.json]');
const directory = realpathSync(resolve(process.argv[2]));
const answerFile = process.argv[3] ?? 'answers.v1.json';
if (!/^answers\.v[1-9][0-9]*\.json$/.test(answerFile)) throw new Error('Invalid answer filename');
const read = name => JSON.parse(readFileSync(resolve(directory, name), 'utf8'));
const report = read('report.json'); const protocol = read('protocol.json');
const queries = read('queries.json'); const gold = read(answerFile); const snapshot = read('snapshot.json');
if (answerFile !== `answers.${gold.answerVersion}.json` || gold.dataset !== queries.dataset || gold.commit !== snapshot.commit) throw new Error('Reference version or dataset mismatch');
if (answerFile !== 'answers.v1.json' && gold.revision?.basedOnSha256 !== sha256(readFileSync(resolve(directory, 'answers.v1.json')))) throw new Error('Reference revision base mismatch');
if (new Set(gold.answers.map(answer => answer.id)).size !== queries.cases.length || gold.answers.length !== queries.cases.length || queries.cases.some(task => !gold.answers.some(answer => answer.id === task.id))) throw new Error('Reference task mismatch');
for (const [name, hash] of Object.entries(read('freeze.json').sha256)) {
  if (sha256(readFileSync(resolve(directory, name))) !== hash) throw new Error('Frozen run input changed');
}
const corpus = realpathSync(resolve(projectRoot, '.pilot-state/django-v1/corpus'));
const sourceLines = new Map(snapshot.files.map(file => {
  const path = realpathSync(resolve(corpus, file.path));
  if (!path.startsWith(corpus + sep)) throw new Error('Invalid corpus path');
  const data = readFileSync(path);
  if (sha256(data) !== file.sha256) throw new Error('Corpus hash mismatch');
  return [file.path, data.toString('utf8').replace(/\r\n/g, '\n').split('\n')];
}));
validateAnswers(gold.answers, sourceLines);
const answers = new Map(gold.answers.map(answer => [answer.id, answer]));
const budgets = [...new Set([protocol.primaryBudgetTokens, ...protocol.supplementalBudgetsTokens])].sort((a, b) => a - b);
mkdirSync(resolve(directory, 'budgeted'), { recursive: true, mode: 0o700 });
const rows = [];
for (const task of queries.cases) for (const language of ['zh', 'en']) {
  const matching = report.results.filter(row => row.id === task.id && row.language === language);
  if (matching.length > 1) throw new Error('Duplicate result for a task-language pair');
  const found = matching[0];
  let raw = '';
  if (found?.status === 'completed') {
    if (found.rawFile !== `${task.id}.${language}.txt`) throw new Error('Unexpected raw response path');
    raw = readFileSync(resolve(directory, found.rawFile), 'utf8');
    if (sha256(raw) !== found.sha256) throw new Error('Raw response changed');
  }
  const answer = answers.get(task.id);
  const rawScore = scoreEvidence(raw, answer, sourceLines);
  const budgetScores = budgets.map(budget => {
    const selected = budgetPrefix(raw, budget);
    const file = `budgeted/${task.id}.${language}.${budget}.txt`;
    writeFileSync(resolve(directory, file), selected.text, { mode: 0o600 });
    return { budget, tokens: selected.tokens, truncated: selected.truncated, file,
      ...scoreEvidence(selected.text, answer, sourceLines) };
  });
  rows.push({ id: task.id, language, status: found?.status ?? 'not-run', rawTokens: tokenCount(raw),
    elapsedMs: found?.elapsedMs ?? null, rawScore, budgetScores });
}
const summary = {};
for (const budget of budgets) {
  summary[budget] = {};
  for (const language of ['zh', 'en']) {
    const group = rows.filter(row => row.language === language);
    const scores = group.map(row => row.budgetScores.find(score => score.budget === budget));
    summary[budget][language] = { tasks: group.length, completed: group.filter(row => row.status === 'completed').length,
      coverage: scores.reduce((sum, score) => sum + score.coverage, 0) / group.length,
      completeRecall: scores.filter(score => score.complete).length / group.length };
  }
  summary[budget].englishMinusChinese = summary[budget].en.coverage - summary[budget].zh.coverage;
}
const result = { schemaVersion: 1, kind: 'development-pilot-reference-span-coverage',
  answerVersion: gold.answerVersion, answerFile, answerSha256: sha256(readFileSync(resolve(directory, answerFile))),
  commit: snapshot.commit, tokenizer: protocol.tokenizer,
  primaryBudget: protocol.primaryBudgetTokens, independentTasks: queries.cases.length,
  notes: ['Source-verified reference-span coverage; no human/independent annotation claim.',
    'Unjudged output is not automatically irrelevant. One run per language; no significance claim.'],
  summary, rows };
const outputFile = `scores.${gold.answerVersion}.json`;
writeFileSync(resolve(directory, outputFile), JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
console.log(JSON.stringify({ summary, saved: resolve(directory, outputFile) }, null, 2));

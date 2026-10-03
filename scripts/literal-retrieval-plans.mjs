// Deterministic query-only baseline for when no generative planner is available.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { sha256 } from '../src/eval/evidence.mjs';
const input = resolve(process.argv[2] ?? 'eval/django-v1/queries.json');
const output = resolve(process.argv[3] ?? '.pilot-state/reponerve/plans.json');
const data = readFileSync(input);
const queries = JSON.parse(data);
const results = queries.cases.flatMap(q => ['zh', 'en'].map(language => {
  const query = q.queries[language];
  const parts = query.split(/[:：;；，]|,\s+(?=how|which|why|where|what)|\s+and\s+(?=how|which|why|where|what)/i).map(s => s.trim()).filter(s => s.length > 7);
  const facets = parts.length > 1 && parts.length <= 4 ? parts : [query];
  return { id: q.id, language, query, elapsedMs: 0, plan: { intent: query,
    facets: facets.map(question => ({ question, terms: question.match(/[A-Za-z][A-Za-z0-9_]*/g) ?? [] })) } };
}));
mkdirSync(resolve(output, '..'), { recursive: true });
writeFileSync(output, JSON.stringify({ version: 1, planner: { model: null, mode: 'literal-clause-split-v1' },
  queriesSha256: sha256(data), instruction: 'Original query plus deterministic clause splitting; no translation, generation, repository access or labels.', results }, null, 2) + '\n');
console.log(JSON.stringify({ output, completed: results.length }));

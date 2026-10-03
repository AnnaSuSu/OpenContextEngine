import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadConfig, publicConfig, projectRoot } from '../src/pilot/config.mjs';
import { responseRequest } from '../src/pilot/responses.mjs';
import { sha256 } from '../src/eval/evidence.mjs';

const input = resolve(process.argv[2] ?? 'eval/django-v1/queries.json');
const output = resolve(process.argv[3] ?? '.pilot-state/reponerve/plans.json');
const queries = JSON.parse(readFileSync(input));
const config = loadConfig();
const schema = { type: 'object', additionalProperties: false, required: ['intent', 'facets'], properties: {
  intent: { type: 'string', description: 'Faithful English translation of the complete request.' },
  facets: { type: 'array', minItems: 1, maxItems: 4, items: { type: 'object', additionalProperties: false,
    required: ['question', 'terms'], properties: {
      question: { type: 'string', description: 'One independently useful behavior or stage to locate, in English.' },
      terms: { type: 'array', minItems: 2, maxItems: 8, items: { type: 'string' }, description: 'Generic lexical search words grounded in the request.' },
    } } },
} };
const report = existsSync(output) ? JSON.parse(readFileSync(output)) : { version: 1, planner: publicConfig(config), queriesSha256: sha256(readFileSync(input)),
  instruction: 'Translate and decompose only; no repository access or reference answers.', results: [] };
mkdirSync(resolve(output, '..'), { recursive: true });
const tasks = queries.cases.flatMap(q => ['zh', 'en'].map(language => ({ id: q.id, language, query: q.queries[language] })));
if (report.queriesSha256 !== sha256(readFileSync(input))) throw new Error('Saved plans belong to different queries');
const pending = tasks.filter(t => !report.results.some(r => r.id === t.id && r.language === t.language));
while (pending.length) {
  await Promise.all(pending.splice(0, 2).map(async task => {
    let result;
    const attemptLog = [];
    for (let attempt = 1; attempt <= 3; attempt++) {
      const started = Date.now();
      try { result = await responseRequest(config, { max_output_tokens: 3000,
      instructions: 'You prepare code search requests. Translate the user request faithfully into English and decompose it into 1 to 4 distinct behavior stages or responsibilities. Keep all qualifications. Do not solve the question. Do not invent file paths, classes, API names, implementation details or repository-specific symbols absent from the request. Use generic English code-search terms. This is a search plan, not an answer.',
      input: [{ role: 'user', content: task.query }], tools: [{ type: 'function', name: 'search_plan', description: 'Return a behavior-oriented search plan.', strict: true, parameters: schema }],
      tool_choice: { type: 'function', name: 'search_plan' },
      }); break; } catch (error) {
        attemptLog.push({ attempt, elapsedMs: Date.now() - started, error: error.message.slice(0, 200) });
        if (attempt === 3 || /HTTP (400|401|403)/.test(error.message)) throw error;
      }
    }
    const call = result.response.output.find(x => x.type === 'function_call' && x.name === 'search_plan');
    if (!call) throw new Error('Planner omitted the search plan');
    const plan = JSON.parse(call.arguments);
    if (!plan.intent || !Array.isArray(plan.facets) || !plan.facets.length || plan.facets.length > 4) throw new Error('Invalid plan');
    report.results.push({ ...task, plan, elapsedMs: result.elapsedMs + attemptLog.reduce((n, r) => n + r.elapsedMs, 0), usage: result.response.usage, attemptLog });
    writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ completed: report.results.length, id: task.id, language: task.language }));
  }));
}
console.log(JSON.stringify({ output, completed: report.results.length }));

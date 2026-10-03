import { readFile } from 'node:fs/promises';
import { resolve, relative, isAbsolute } from 'node:path';

/** Deterministic evidence-location proxy, NOT a semantic answer grader. */
export async function scoreEvidence(raw, task, corpus) {
  let answer;
  try { answer = JSON.parse(raw); } catch { return { validJson: false, coverage: 0, complete: false, invalidEvidence: 1 }; }
  if (!Array.isArray(answer?.evidence) || typeof answer.answer !== 'string') {
    return { validJson: false, coverage: 0, complete: false, invalidEvidence: 1 };
  }
  const valid = [];
  const invalid = [];
  for (const evidence of answer.evidence) {
    try {
      if (typeof evidence.path !== 'string' || isAbsolute(evidence.path)) throw new Error('Path must be relative');
      const target = resolve(corpus, evidence.path);
      if (relative(corpus, target).startsWith('..')) throw new Error('Path escapes corpus');
      const lines = (await readFile(target, 'utf8')).split('\n');
      if (!Number.isInteger(evidence.start_line) || !Number.isInteger(evidence.end_line) ||
          evidence.start_line < 1 || evidence.end_line < evidence.start_line || evidence.end_line > lines.length ||
          evidence.end_line - evidence.start_line + 1 > 40) throw new Error('Invalid range or more than 40 lines');
      const text = lines.slice(evidence.start_line - 1, evidence.end_line).join('\n');
      if (!evidence.quote?.trim() || text.trim() !== evidence.quote.trim()) throw new Error('Quote does not match the complete source range');
      valid.push({ path: evidence.path, text });
    } catch (error) { invalid.push({ path: evidence?.path ?? null, reason: error.message }); }
  }
  const units = task.units.map(unit => ({ id: unit.id, covered: unit.anchors.every(anchor =>
    valid.some(e => e.path === unit.path && e.text.includes(anchor))) }));
  const budgetOk = raw.length <= 16000 && answer.evidence.length <= 8;
  const coverage = budgetOk ? units.filter(u => u.covered).length / units.length : 0;
  return { validJson: true, budgetOk, coverage, complete: coverage === 1, units,
    validEvidence: valid.length, invalidEvidence: invalid.length, invalid,
    finalResponseChars: raw.length, semanticAnswerCorrectness: 'requires-human-review' };
}

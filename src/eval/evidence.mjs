import { getEncoding } from 'js-tiktoken';
import { createHash } from 'node:crypto';

const encoding = getEncoding('cl100k_base');
export const sha256 = value => createHash('sha256').update(value).digest('hex');
export const tokenCount = text => encoding.encode(text).length;

// The budget policy cannot see the labels or select/reorder code sections.
export function budgetPrefix(raw, budget) {
  if (!Number.isInteger(budget) || budget <= 0) throw new Error('Invalid token budget');
  const tokens = encoding.encode(raw);
  if (tokens.length <= budget) return { text: raw, tokens: tokens.length, truncated: false };
  let text = encoding.decode(tokens.slice(0, budget));
  // Avoid a partial UTF-8 character or a partial code line receiving credit.
  text = text.slice(0, text.lastIndexOf('\n') + 1);
  while (text && (!raw.startsWith(text) || tokenCount(text) > budget)) {
    text = text.slice(0, text.slice(0, -1).lastIndexOf('\n') + 1);
  }
  return { text, tokens: tokenCount(text), truncated: true };
}

export function parseAndVerify(raw, sourceLines) {
  const verified = new Map();
  const invalid = [];
  let path = null;
  let numberedLines = 0;
  let verifiedOccurrences = 0;
  for (const row of raw.split(/\r?\n/)) {
    if (row.startsWith('Path: ')) {
      path = row.slice(6).trim().replace(/^\.\//, '');
      continue;
    }
    const match = /^\s*(\d+)\t(.*)$/.exec(row);
    if (!match) continue;
    numberedLines++;
    const line = Number(match[1]);
    const source = sourceLines.get(path);
    if (!source || !Number.isSafeInteger(line) || line < 1 || line > source.length || source[line - 1] !== match[2]) {
      invalid.push({ path, line, reason: !source ? 'unknown-path' : 'line-text-mismatch' });
      continue;
    }
    verifiedOccurrences++;
    if (!verified.has(path)) verified.set(path, new Set());
    verified.get(path).add(line);
  }
  const uniqueVerifiedLines = [...verified.values()].reduce((sum, lines) => sum + lines.size, 0);
  return { verified, diagnostic: { numberedLines, verifiedOccurrences, uniqueVerifiedLines,
    duplicateVerifiedLines: verifiedOccurrences - uniqueVerifiedLines, invalid } };
}

export function validateAnswers(answers, sourceLines) {
  const ids = new Set();
  for (const task of answers) {
    if (ids.has(task.id) || !task.units?.length) throw new Error('Invalid answer task');
    ids.add(task.id);
    const units = new Set();
    for (const unit of task.units) {
      if (units.has(unit.id) || !unit.fact || !unit.alternatives?.length) throw new Error('Invalid evidence unit');
      units.add(unit.id);
      for (const alternative of unit.alternatives) {
        if (!alternative.allOf?.length) throw new Error('Empty evidence alternative');
        for (const span of alternative.allOf) {
          const source = sourceLines.get(span.path);
          if (!source || !Number.isInteger(span.startLine) || !Number.isInteger(span.endLine) ||
            span.startLine < 1 || span.endLine < span.startLine || span.endLine > source.length) {
            throw new Error(`Invalid reference span: ${task.id}/${unit.id}`);
          }
          const actual = source.slice(span.startLine - 1, span.endLine).join('\n');
          if (actual !== span.quote || sha256(actual) !== span.sha256) {
            throw new Error(`Reference source changed: ${task.id}/${unit.id}`);
          }
        }
      }
    }
  }
}

export function scoreEvidence(text, answer, sourceLines) {
  if (!answer.units?.length) throw new Error('Cannot score an empty reference');
  const { verified, diagnostic } = parseAndVerify(text, sourceLines);
  const units = answer.units.map(unit => {
    const alternatives = unit.alternatives.map(alternative => ({
      missing: alternative.allOf.flatMap(span => {
        const missingLines = [];
        for (let line = span.startLine; line <= span.endLine; line++) {
          if (!verified.get(span.path)?.has(line)) missingLines.push(line);
        }
        return missingLines.length ? [{ path: span.path, missingLines }] : [];
      }),
    }));
    return { id: unit.id, fact: unit.fact, covered: alternatives.some(a => a.missing.length === 0), alternatives };
  });
  const covered = units.filter(unit => unit.covered).length;
  return { covered, total: units.length, coverage: covered / units.length,
    omission: 1 - covered / units.length, complete: covered === units.length, units, diagnostic };
}

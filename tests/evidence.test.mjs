import test from 'node:test';
import assert from 'node:assert/strict';
import { sha256, tokenCount, budgetPrefix, parseAndVerify, validateAnswers, scoreEvidence } from '../src/eval/evidence.mjs';

const source = new Map([
  ['django/a.py', ['def login():', '    verify_password()', '    save_session()', '    return True']],
  ['django/b.py', ['def alternative():', '    authenticate_and_save()']],
]);
const span = (path, startLine, endLine = startLine) => {
  const quote = source.get(path).slice(startLine - 1, endLine).join('\n');
  return { path, startLine, endLine, quote, sha256: sha256(quote) };
};
const answer = { id: 'login', units: [{ id: 'identity-and-session', fact: 'verify and persist', alternatives: [
  { allOf: [span('django/a.py', 2), span('django/a.py', 3)] },
  { allOf: [span('django/b.py', 2)] },
] }] };

test('Evidence needs all complementary snippets, but accepts a complete alternative', () => {
  validateAnswers([answer], source);
  assert.equal(scoreEvidence('Path: django/a.py\n2\t    verify_password()\n', answer, source).coverage, 0);
  assert.equal(scoreEvidence('Path: django/a.py\n2\t    verify_password()\n3\t    save_session()\n', answer, source).coverage, 1);
  assert.equal(scoreEvidence('Path: django/b.py\n2\t    authenticate_and_save()\n', answer, source).coverage, 1);
});

test('Correct paths with fabricated text, wrong line numbers, or escaped paths receive no credit', () => {
  for (const raw of ['Path: django/a.py\n2\t    save_session()\n',
    'Path: django/b.py\n99\t    authenticate_and_save()\n',
    'Path: ../django/b.py\n2\t    authenticate_and_save()\n']) {
    const result = scoreEvidence(raw, answer, source);
    assert.equal(result.coverage, 0);
    assert.equal(result.diagnostic.invalid.length, 1);
  }
});

test('Source changes invalidate frozen reference quotes even when a line still exists', () => {
  const changed = new Map(source);
  changed.set('django/a.py', ['def login():', '    skip_password()', '    save_session()', '    return True']);
  assert.throws(() => validateAnswers([answer], changed), /Reference source changed/);
});

test('Budgeting preserves ranked prefix, counts metadata, and never credits a cut source line', () => {
  const prefix = 'The following sections:\nPath: django/a.py\n1\tdef login():\n';
  const raw = prefix + '2\t    verify_password()\n3\t    save_session()\n' + '背景😀'.repeat(100);
  const budget = tokenCount(prefix) + 2;
  const limited = budgetPrefix(raw, budget);
  assert.ok(raw.startsWith(limited.text));
  assert.ok(limited.tokens <= budget);
  assert.ok(limited.text.endsWith('\n'));
  assert.equal(scoreEvidence(limited.text, answer, source).coverage, 0);
  assert.equal(budgetPrefix(raw, tokenCount(raw)).text, raw);
});

test('Duplicates and empty responses do not inflate coverage', () => {
  const raw = 'Path: django/b.py\n2\t    authenticate_and_save()\n2\t    authenticate_and_save()\n';
  const result = parseAndVerify(raw, source);
  assert.equal(result.diagnostic.uniqueVerifiedLines, 1);
  assert.equal(result.diagnostic.duplicateVerifiedLines, 1);
  assert.equal(scoreEvidence('', answer, source).coverage, 0);
  assert.equal(scoreEvidence('', answer, source).complete, false);
});

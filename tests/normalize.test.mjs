import test from 'node:test';
import assert from 'node:assert/strict';
import { renderBlocks, cocoBlocks, contextWeaverBlocks } from '../src/eval/normalize.mjs';
import { parseAndVerify } from '../src/eval/evidence.mjs';

test('Normalization preserves engine order and partial lines without completing them from source', () => {
  const result = renderBlocks(cocoBlocks([
    { file_path: '/corpus/b.py', start_line: 2, content: '    return\n' },
    { file_path: 'a.py', start_line: 1, content: 'def f():\n    pass' },
  ]), '/corpus');
  assert.equal(result, 'Path: b.py\n2\t    return\n\nPath: a.py\n1\tdef f():\n2\t    pass\n');
  const parsed = parseAndVerify(result, new Map([
    ['b.py', ['def g():', '    return 1']], ['a.py', ['def f():', '    pass']],
  ]));
  assert.equal(parsed.diagnostic.invalid.length, 1);
  assert.equal(parsed.diagnostic.uniqueVerifiedLines, 2);
});

test('ContextWeaver segment order and line coordinates are preserved; outside-root paths are rejected', () => {
  const blocks = contextWeaverBlocks({ version: 1, files: [{ filePath: 'a.py', segments: [
    { startLine: 20, text: 'last' }, { startLine: 3, text: 'first' },
  ] }] });
  assert.equal(renderBlocks(blocks, '/corpus'), 'Path: a.py\n20\tlast\n\nPath: a.py\n3\tfirst\n');
  assert.throws(() => renderBlocks([{ path: '/private.py', startLine: 1, text: 'x' }], '/corpus'));
});

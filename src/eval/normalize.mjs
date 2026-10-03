import { isAbsolute, relative } from 'node:path';

// Rendering only: never read the corpus to expand, repair, or reorder results.
export function renderBlocks(blocks, corpusRoot) {
  return blocks.map(block => {
    const path = isAbsolute(block.path) ? relative(corpusRoot, block.path) : block.path;
    if (path.startsWith('../') || isAbsolute(path) || /[\r\n]/.test(path)) throw new Error('Invalid returned path');
    if (!Number.isSafeInteger(block.startLine) || block.startLine < 1 || typeof block.text !== 'string') throw new Error('Invalid returned span');
    const lines = block.text.split('\n');
    if (lines.at(-1) === '') lines.pop();
    return `Path: ${path}\n` + lines.map((line, i) => `${block.startLine + i}\t${line}`).join('\n');
  }).join('\n\n') + (blocks.length ? '\n' : '');
}

export function cocoBlocks(results) {
  if (!Array.isArray(results)) throw new Error('Invalid CocoIndex output');
  return results.map(row => ({ path: row.file_path, startLine: row.start_line, text: row.content }));
}

export function contextWeaverBlocks(result) {
  if (result.version !== 1 || !Array.isArray(result.files)) throw new Error('Invalid ContextWeaver output');
  return result.files.flatMap(file => file.segments.map(segment => ({
    path: file.filePath, startLine: segment.startLine, text: segment.text,
  })));
}

import {renderBlocks} from '../../src/eval/normalize.mjs';
// grepai prepends a display header to chunk.content. It is not a source line.
// Preserve the code and native ordering; replace that metadata with our path header.
export function normalizeGrepai(rows,corpusRoot){
 if(!Array.isArray(rows))throw Error('Invalid grepai output');
 return renderBlocks(rows.map(row=>{
  const header=`File: ${row.file_path}\n\n`;
  if(typeof row.content!=='string'||!row.content.startsWith(header))throw Error('Unexpected grepai display header');
  return {path:row.file_path,startLine:row.start_line,text:row.content.slice(header.length)};
 }),corpusRoot);
}

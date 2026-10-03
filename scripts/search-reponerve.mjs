import {search} from '../src/client.mjs';
const query=process.argv.slice(2).join(' ').trim();
if (!query) throw new Error('Usage: node scripts/search-reponerve.mjs "Describe the code you need"');
const result=await search(query);
console.log(result.context);
console.error(JSON.stringify({elapsedMs:result.clientElapsedMs,retrievalMs:result.retrievalMs,tokens:result.tokens,queryCache:result.queryCache}));

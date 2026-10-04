import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { search, indexStatus } from './client.mjs';

export function createMcpServer(config) {
  const server = new McpServer({name:'opencontextengine',version:'0.1.0'}, {
    instructions:'Search the configured repository for source evidence. Results include source paths and line numbers. '
      + 'Search waits for saved file changes to be indexed. If an update is pending or fails, inspect index_status and retry after it completes. '
      + 'Read target files again before editing, because code may change after a search.',
  });
  const annotations = {readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false};
  server.registerTool('search_code', {
    title:'Search repository source',
    description:'Find code implementing a task or behavior in this repository. Returns source evidence under a token budget. '
      + 'Uses saved working-tree content, including uncommitted changes; rejects stale results when synchronization fails.',
    inputSchema:{query:z.string().trim().min(1).max(8192),budget:z.number().int().min(256).max(8000).default(4000),
      freshnessWaitMs:z.number().int().min(0).max(120000).default(30000)},
    annotations,
  }, async ({query,budget,freshnessWaitMs}, extra) => {
    try {
      const result = await search(query,{budget,freshnessWaitMs,config,signal:extra.signal});
      if (result.index?.mode !== 'live') throw new Error('This service uses a frozen index; connect to a service started with --root');
      return {content:[{type:'text',text:result.context || 'No matching source context.'}],structuredContent:result};
    } catch (error) {
      return {isError:true,content:[{type:'text',text:error.message}]};
    }
  });
  server.registerTool('index_status', {
    title:'Repository index status',
    description:'Inspect the configured repository, synchronization state, current generation, embedding reuse and last update error. '
      + 'Status is the latest background observation; search_code actively checks source freshness.',
    inputSchema:{},annotations,
  }, async (_,extra) => {
    try {
      const result = await indexStatus({config,signal:extra.signal});
      return {content:[{type:'text',text:JSON.stringify(result)}],structuredContent:result};
    } catch (error) {
      return {isError:true,content:[{type:'text',text:error.message}]};
    }
  });
  return server;
}

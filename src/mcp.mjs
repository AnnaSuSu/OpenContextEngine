import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { search, indexStatus } from './client.mjs';

function updatingResult(error) {
  const progress = error.index?.progress;
  let detail = '';
  if (progress?.stage === 'embedding') {
    detail = ` Embedding documents: ${progress.completedDocuments}/${progress.totalDocuments} completed for this update.`;
  } else if (progress?.stage === 'parsing') {
    detail = ` Parsing ${progress.files} files.`;
  } else if (progress?.stage === 'finalizing') {
    detail = ' Finalizing the searchable index.';
  } else if (progress?.stage === 'source_changed') {
    detail = ' Saved files changed during indexing; synchronizing the latest version.';
  }
  return {isError:false,
    content:[{type:'text',text:'Index is updating; search has not run yet.' + detail
      + ' Background synchronization continues. Check index_status for this project and retry search_code once ready.'}],
    structuredContent:{status:'updating',code:'INDEX_UPDATING',retryable:true,index:error.index}};
}

export function createMcpServer(config, {resolveConfig, automatic = false} = {}) {
  const workspaceInstructions = automatic
    ? 'Pass directory_path as the absolute directory of the project the user is working on with every tool call. '
      + 'Use the workspace path supplied by your host or inspect the current project directory; do not guess it. '
      + 'A new project is indexed on first access. The same server can search multiple projects independently. '
    : 'This server searches one configured repository. ';
  async function selectConfig(directoryPath) {
    if (resolveConfig) return resolveConfig(directoryPath);
    if (directoryPath !== undefined) throw new Error('Connected-service mode uses its configured repository; omit directory_path');
    return config;
  }
  const pathSchema = z.string().min(1).describe('Absolute path to the project directory. Required in automatic workspace mode.');
  const directoryPath = automatic ? pathSchema : pathSchema.optional();
  const server = new McpServer({name:'open-context-engine',version:'0.1.5'}, {
    instructions:workspaceInstructions + 'Search for source evidence. Results include source paths and line numbers. '
      + 'Search waits for saved file changes and retries a pending update once. A status of updating means search has not run; inspect index_status and retry once ready. '
      + 'Read target files again before editing, because code may change after a search.',
  });
  const annotations = {readOnlyHint:true,destructiveHint:false,idempotentHint:true,openWorldHint:false};
  server.registerTool('search_code', {
    title:'Search repository source',
    description:'Find code implementing a task or behavior in a repository. Returns source evidence under a token budget. '
      + workspaceInstructions
      + 'Uses saved working-tree content, including uncommitted changes; rejects stale results when synchronization fails.',
    inputSchema:{directory_path:directoryPath,query:z.string().trim().min(1).max(8192),budget:z.number().int().min(256).max(8000).default(8000),
      freshnessWaitMs:z.number().int().min(0).max(120000).default(30000)
        .describe('Initial synchronization wait. Pending updates are retried once for up to 10 additional seconds; 0 disables waiting and retry.')},
    annotations,
  }, async ({directory_path,query,budget,freshnessWaitMs}, extra) => {
    try {
      const selected = await selectConfig(directory_path);
      let result;
      try {
        result = await search(query,{budget,freshnessWaitMs,config:selected,signal:extra.signal});
      } catch (error) {
        extra.signal.throwIfAborted();
        if (error.code !== 'INDEX_UPDATING' || freshnessWaitMs === 0) throw error;
        result = await search(query,{budget,freshnessWaitMs:Math.min(freshnessWaitMs,10000),config:selected,signal:extra.signal});
      }
      if (result.index?.mode !== 'live') throw new Error('This service uses a frozen index; connect to a service started with --root');
      const warning = result.index.degradedFiles
        ? `Note: ${result.index.degradedFiles} file(s) indexed as plain text after syntax errors; inspect index_status for paths and locations.\n\n` : '';
      return {content:[{type:'text',text:warning + (result.context || 'No matching source context.')}],structuredContent:result};
    } catch (error) {
      if (error.code === 'INDEX_UPDATING') return updatingResult(error);
      return {isError:true,content:[{type:'text',text:error.message}]};
    }
  });
  server.registerTool('index_status', {
    title:'Repository index status',
    description:'Inspect repository synchronization, current generation, embedding reuse and last update error. '
      + workspaceInstructions
      + 'Status is the latest background observation; search_code actively checks source freshness.',
    inputSchema:{directory_path:directoryPath},annotations,
  }, async ({directory_path},extra) => {
    try {
      const selected = await selectConfig(directory_path);
      const result = await indexStatus({config:selected,signal:extra.signal});
      return {content:[{type:'text',text:JSON.stringify(result)}],structuredContent:result};
    } catch (error) {
      return {isError:true,content:[{type:'text',text:error.message}]};
    }
  });
  return server;
}

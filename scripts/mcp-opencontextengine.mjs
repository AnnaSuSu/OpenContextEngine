import { parseArgs } from 'node:util';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createMcpServer } from '../src/mcp.mjs';
import { clientConfig } from '../src/client.mjs';
import { createWorkspaceManager } from '../src/workspaces.mjs';

const {values} = parseArgs({options:{root:{type:'string'},state:{type:'string'},connect:{type:'boolean'}}});
if (values.connect && (values.root !== undefined || values.state !== undefined) || values.root === '' || values.state === '') {
  throw new Error('Usage: node scripts/mcp-opencontextengine.mjs [--root /repository] [--state /outside/index] OR --connect');
}
let workspaces, server, stopping = false;
async function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  try {
    await server?.close();
  } finally {
    await workspaces?.close();
    process.exit(code);
  }
}
process.once('SIGINT', () => {void shutdown();});
process.once('SIGTERM', () => {void shutdown();});
process.stdin.once('end', () => {void shutdown();});
try {
  if (values.connect) {
    server = createMcpServer(clientConfig());
  } else {
    workspaces = createWorkspaceManager(values);
    if (values.root) await workspaces.get();
    if (!stopping) server = createMcpServer(undefined, {resolveConfig:workspaces.get, automatic:!values.root});
  }
  if (!stopping) await server.connect(new StdioServerTransport());
} catch (error) {
  process.stderr.write(`OpenContextEngine MCP startup failed: ${error.message}\n`);
  await shutdown(1);
}

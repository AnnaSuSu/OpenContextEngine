import { parseArgs } from 'node:util';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createMcpServer } from '../src/mcp.mjs';
import { clientConfig } from '../src/client.mjs';
import { serviceConfig, startService } from '../src/service.mjs';

const {values} = parseArgs({options:{root:{type:'string'},state:{type:'string'},connect:{type:'boolean'}}});
if (Boolean(values.root) === Boolean(values.connect) || values.connect && values.state) {
  throw new Error('Usage: node scripts/mcp-opencontextengine.mjs --root /repository [--state /outside/index] OR --connect');
}
let worker, server, stopping = false;
async function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  try {
    await server?.close();
  } finally {
    await worker?.close();
    process.exit(code);
  }
}
process.once('SIGINT', () => {void shutdown();});
process.once('SIGTERM', () => {void shutdown();});
process.stdin.once('end', () => {void shutdown();});
try {
  worker = values.root ? startService(serviceConfig(values)) : null;
  if (worker) worker.child.once('exit', () => {if (!stopping) void shutdown(1);});
  const config = worker ? await worker.ready : clientConfig();
  server = createMcpServer(config);
  await server.connect(new StdioServerTransport());
} catch (error) {
  process.stderr.write(`OpenContextEngine MCP startup failed: ${error.message}\n`);
  await shutdown(1);
}

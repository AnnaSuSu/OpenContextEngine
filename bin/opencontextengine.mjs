#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { setup, validateModels } from '../src/setup.mjs';
import { loadEnvironment, configDirectory } from '../src/config.mjs';
import { verifyPython, run } from '../src/runtime.mjs';
import { serviceConfig } from '../src/service.mjs';

const help = `OpenContextEngine — repository context for AI coding agents

Usage:
  open-context-engine setup [--python <interpreter-path>] [--non-interactive]
  open-context-engine mcp [--root /project] [--state /outside/index]
  open-context-engine mcp --connect
  open-context-engine mcp-config
  open-context-engine doctor
  open-context-engine --version

Setup installs isolated Python dependencies, saves shared model settings, and
prints MCP configuration. Without --root, your agent supplies directory_path.
Requires macOS/Linux/Windows, Node.js 22.14+, Python 3.10+, and Git.
`;
function mcpConfig() {
  const env = process.env.OCE_CONFIG_HOME ? {OCE_CONFIG_HOME:configDirectory()} : undefined;
  console.log(JSON.stringify({mcpServers:{'open-context-engine':{command:process.execPath,
    args:[fileURLToPath(import.meta.url),'mcp'],...(env ? {env} : {})}}},null,2));
}
try {
  const [command,...args] = process.argv.slice(2);
  if (!command || command === '--help' || command === '-h' || args.includes('--help')) {
    console.log(help);
  } else if (command === '--version' || command === '-v') {
    console.log(JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8')).version);
  } else if (command === 'setup') {
    const {values} = parseArgs({args,options:{python:{type:'string'},'non-interactive':{type:'boolean'}}});
    await setup({python:values.python,nonInteractive:Boolean(values['non-interactive'])});
    mcpConfig();
  } else if (command === 'mcp-config' && args.length === 0) {
    mcpConfig();
  } else if (command === 'doctor' && args.length === 0) {
    const env = loadEnvironment();
    validateModels(env);
    await run('git',['--version'],{timeout:10000});
    const python = serviceConfig().python;
    const version = await verifyPython(python,env);
    console.log(`Model configuration valid. Python ${version}, NumPy, tiktoken, and Git are ready.`);
    console.log('Endpoint authentication is checked during search. Go projects also require Go 1.22+.');
  } else if (command === 'mcp') {
    // Keep stdout exclusively for MCP messages. Setup remains a separate terminal command.
    if (!args.includes('--connect')) {
      validateModels(loadEnvironment());
      await verifyPython(serviceConfig().python,loadEnvironment());
    }
    process.argv.splice(2,1);
    await import('../scripts/mcp-opencontextengine.mjs');
  } else {
    throw new Error('Unknown command or arguments. Run open-context-engine --help');
  }
} catch (error) {
  process.stderr.write(`OpenContextEngine: ${error.message}\n`);
  process.stderr.write('Run open-context-engine setup to configure models and install Python dependencies.\n');
  process.exitCode = 1;
}

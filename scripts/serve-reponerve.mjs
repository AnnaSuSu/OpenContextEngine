import { parseArgs } from 'node:util';
import { serviceConfig, startService } from '../src/service.mjs';
const {values} = parseArgs({options: {
  root:{type:'string'}, state:{type:'string'}, port:{type:'string',default:'23505'},
}});
const port = Number(values.port);
if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Invalid port');
const settings = serviceConfig({...values,port});
const {clientConfig} = await import('../src/client.mjs');
settings.config.serviceKey = clientConfig().apiKey;
if (settings.config.serviceKey.length < 24) throw new Error('Set a strong REPONERVE_API_KEY (at least 24 characters)');
const worker = startService(settings);
process.once('SIGTERM', async () => {await worker.close(); process.exit(0);});
process.once('SIGINT', async () => {await worker.close(); process.exit(0);});
worker.child.once('exit', code => {process.exitCode = code ?? 1;});
const client = await worker.ready;
console.log(JSON.stringify({listening:client.baseUrl, mode:values.root ? 'live' : 'frozen', state:settings.config.state}));

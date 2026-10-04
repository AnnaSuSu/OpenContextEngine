import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, mkdir, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join, dirname, relative, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';
import { configDirectory, projectRoot } from './config.mjs';

const exec = promisify(execFile);
export function defaultPython(platform = process.platform) {
  return platform === 'win32' ? 'python' : 'python3';
}
export function venvPython(directory, platform = process.platform) {
  return platform === 'win32' ? join(directory,'Scripts','python.exe') : join(directory,'bin','python');
}
export async function run(command, args, options = {}) {
  try {return await exec(command,args,{timeout:600000,maxBuffer:4*1024*1024,...options});}
  catch (error) {
    // Do not echo pip output: configured package indexes may contain credentials.
    throw new Error(`${command} failed (${error.code || 'unknown'}). Check the executable, network, and Python venv/pip support.`);
  }
}
const probe = 'import sys, importlib.metadata as m; assert sys.version_info >= (3,10); import numpy,tiktoken; '
  + 'n=tuple(map(int,m.version("numpy").split(".")[:2])); t=tuple(map(int,m.version("tiktoken").split(".")[:2])); '
  + 'assert (2,2)<=n<(3,0) and (0,9)<=t<(1,0); tiktoken.get_encoding("cl100k_base"); print(sys.version.split()[0])';

export async function verifyPython(python, environment = process.env, execute = run) {
  return (await execute(python,['-c',probe],{env:environment,timeout:120000})).stdout.trim();
}

export async function ensureRuntime(environment, {platform = process.platform,
  python = defaultPython(platform), execute = run, log = () => {}} = {}) {
  const runtimes = join(configDirectory(environment),'runtimes');
  const requirements = await readFile(join(projectRoot,'requirements.txt'));
  const fingerprint = createHash('sha256').update(requirements).digest('hex');
  const current = environment.OCE_PYTHON;
  const child = current && relative(runtimes,current);
  if (current && child && !child.startsWith('..') && !isAbsolute(child)) {
    try {
      const directory = dirname(dirname(current));
      const manifest = JSON.parse(await readFile(join(directory,'ready.json'),'utf8'));
      if (manifest.requirementsSha256 === fingerprint) {
        const env = {...environment,TIKTOKEN_CACHE_DIR:join(directory,'tokenizer')};
        await verifyPython(current,env,execute);
        log('Reusing the installed Python runtime.');
        return {OCE_PYTHON:current,TIKTOKEN_CACHE_DIR:env.TIKTOKEN_CACHE_DIR};
      }
    } catch { /* Rebuild separately; the existing runtime and config remain intact. */ }
  }
  await execute(python,['-c','import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'],{timeout:10000});
  await mkdir(runtimes,{recursive:true,mode:0o700});
  // Virtual environments cannot be relocated. Each installation is built in its final directory.
  const directory = await mkdtemp(join(runtimes,'python-'));
  const executable = venvPython(directory,platform);
  const env = {...environment,TIKTOKEN_CACHE_DIR:join(directory,'tokenizer')};
  try {
    log('Creating an isolated Python environment...');
    await execute(python,['-m','venv',directory]);
    log('Installing NumPy and tiktoken (no model weights)...');
    await execute(executable,['-m','pip','install','--disable-pip-version-check','--no-input','-r',join(projectRoot,'requirements.txt')]);
    await verifyPython(executable,env,execute);
    await writeFile(join(directory,'ready.json'),JSON.stringify({requirementsSha256:fingerprint})+'\n',{mode:0o600});
    return {OCE_PYTHON:executable,TIKTOKEN_CACHE_DIR:env.TIKTOKEN_CACHE_DIR};
  } catch (error) {
    await rm(directory,{recursive:true,force:true});
    throw error;
  }
}

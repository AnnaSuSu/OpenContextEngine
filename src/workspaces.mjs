import { realpathSync, statSync } from 'node:fs';
import { isAbsolute, resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { serviceConfig } from './service.mjs';
import { startSharedService } from './shared-service.mjs';
import { loadEnvironment } from './config.mjs';

function directory(path) {
  const canonical = realpathSync.native(path);
  if (!statSync(canonical).isDirectory()) throw new Error('directory_path must point to a directory');
  return canonical;
}

// Each manager holds one lease per canonical repository, including while connecting.
export function createWorkspaceManager({root, state} = {}, {configure = serviceConfig, start = startSharedService,
  idleMs = Number(loadEnvironment().OCE_WORKSPACE_IDLE_SECONDS || 120)*1000,
  maxWorkspaces = Number(loadEnvironment().OCE_MAX_WORKSPACES || 3)} = {}) {
  const fixedRoot = root ? directory(resolve(root)) : undefined;
  const workers = new Map();
  let closing = false, closed;
  if (!Number.isFinite(idleMs) || idleMs < 10 || !Number.isInteger(maxWorkspaces) || maxWorkspaces < 1) {
    throw new Error('Invalid workspace resource limits');
  }
  const retiring = new Set();
  function retire(repository, entry) {
    if (workers.get(repository) !== entry) return;
    workers.delete(repository);
    const promise = entry.worker.close().catch(() => {}).finally(() => retiring.delete(promise));
    retiring.add(promise);
  }
  const timer = setInterval(() => {
    for (const [repository, entry] of workers) {
      if (entry.settled && Date.now()-entry.lastUsed >= idleMs) retire(repository, entry);
    }
  }, Math.min(1000, idleMs));
  timer.unref();

  async function get(directoryPath) {
    if (closing) throw new Error('MCP workspace manager is shutting down');
    if (directoryPath !== undefined && (typeof directoryPath !== 'string' || !isAbsolute(directoryPath))) {
      throw new Error('directory_path must be an absolute project directory');
    }
    if (!directoryPath && !fixedRoot) {
      throw new Error('Pass directory_path with the absolute path of the project to search, or start MCP with --root');
    }
    const repository = directoryPath ? directory(directoryPath) : fixedRoot;
    if (fixedRoot && repository !== fixedRoot) {
      throw new Error('This MCP server is fixed to --root; omit --root at startup to search multiple projects');
    }
    let entry = workers.get(repository);
    if (!entry) {
      if (workers.size >= maxWorkspaces) {
        const oldest = [...workers].filter(([, item]) => item.settled)
          .sort((a,b) => a[1].lastUsed-b[1].lastUsed)[0];
        if (!oldest) throw new Error('Workspace startup capacity reached; retry after a pending project is ready');
        retire(...oldest);
      }
      const workspaceState = state && (fixedRoot ? state : join(resolve(state),
        createHash('sha256').update(repository).digest('hex').slice(0, 24)));
      const worker = start(configure({root:repository, state:workspaceState}));
      entry = {worker, lastUsed:Date.now(), settled:false};
      workers.set(repository, entry);
      const remove = () => {if (workers.get(repository) === entry) workers.delete(repository);};
      worker.child?.once('exit', remove);
      entry.ready = worker.ready.then(result => {entry.settled=true; return result;}).catch(async error => {
        try {await worker.close();} finally {remove();}
        throw error;
      });
    }
    entry.lastUsed = Date.now();
    await entry.ready;
    entry.lastUsed = Date.now();
    return entry.worker.get ? entry.worker.get() : entry.ready;
  }

  function close() {
    if (!closed) {
      closing = true;
      clearInterval(timer);
      closed = Promise.allSettled([...retiring, ...[...workers.values()].map(entry => entry.worker.close())]).then(results => {
        workers.clear();
        const errors = results.filter(result => result.status === 'rejected').map(result => result.reason);
        if (errors.length) throw new AggregateError(errors, 'Failed to close repository workers');
      });
    }
    return closed;
  }
  return {get, close};
}

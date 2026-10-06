import { realpathSync, statSync } from 'node:fs';
import { isAbsolute, resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { serviceConfig } from './service.mjs';
import { startSharedService } from './shared-service.mjs';

function directory(path) {
  const canonical = realpathSync.native(path);
  if (!statSync(canonical).isDirectory()) throw new Error('directory_path must point to a directory');
  return canonical;
}

// Each manager holds one lease per canonical repository, including while connecting.
export function createWorkspaceManager({root, state} = {}, {configure = serviceConfig, start = startSharedService} = {}) {
  const fixedRoot = root ? directory(resolve(root)) : undefined;
  const workers = new Map();
  let closing = false, closed;

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
      const workspaceState = state && (fixedRoot ? state : join(resolve(state),
        createHash('sha256').update(repository).digest('hex').slice(0, 24)));
      const worker = start(configure({root:repository, state:workspaceState}));
      entry = {worker};
      workers.set(repository, entry);
      const remove = () => {if (workers.get(repository) === entry) workers.delete(repository);};
      worker.child?.once('exit', remove);
      entry.ready = worker.ready.catch(async error => {
        try {await worker.close();} finally {remove();}
        throw error;
      });
    }
    await entry.ready;
    return entry.worker.get ? entry.worker.get() : entry.ready;
  }

  function close() {
    if (!closed) {
      closing = true;
      closed = Promise.allSettled([...workers.values()].map(entry => entry.worker.close())).then(results => {
        workers.clear();
        const errors = results.filter(result => result.status === 'rejected').map(result => result.reason);
        if (errors.length) throw new AggregateError(errors, 'Failed to close repository workers');
      });
    }
    return closed;
  }
  return {get, close};
}

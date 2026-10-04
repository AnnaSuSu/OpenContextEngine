// Isolate ContextWeaver's hard-coded user state without changing its search code.
import os from 'node:os';
import { realpathSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { projectRoot } from '../../src/pilot/config.mjs';
const directory = realpathSync(process.env.BASELINE_STATE_DIR ?? '');
if (!directory.startsWith(resolve(projectRoot, '.pilot-state/method-comparison-v1') + sep)) throw new Error('Invalid baseline state directory');
os.homedir = () => directory;

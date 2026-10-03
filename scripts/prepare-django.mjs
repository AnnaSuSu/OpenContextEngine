import { readFileSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs';
import { resolve, dirname, sep } from 'node:path';
import { execFileSync } from 'node:child_process';
import { projectRoot } from '../src/pilot/config.mjs';
import { sha256 } from '../src/eval/evidence.mjs';

const source = realpathSync(resolve(process.argv[2] || '.pilot-state/django-git'));
const snapshot = JSON.parse(readFileSync(resolve(projectRoot, 'eval/django-v1/snapshot.json'), 'utf8'));
const head = execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
if (head !== snapshot.commit) throw new Error('Check out the frozen Django commit first');
for (const file of snapshot.files) {
  const path = realpathSync(resolve(source, file.path));
  if (!path.startsWith(source + sep)) throw new Error('Source path escapes checkout');
  const data = readFileSync(path);
  if (data.length !== file.bytes || sha256(data) !== file.sha256) throw new Error(`Modified source: ${file.path}`);
  const target = resolve(projectRoot, '.pilot-state/django-v1/corpus', file.path);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, data);
}
console.log(JSON.stringify({ commit: head, files: snapshot.files.length, status: 'prepared' }));

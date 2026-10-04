import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

const exec = promisify(execFile);
const destination = resolve(process.argv[2] || '.pilot-state/npm-release');
const stage = await mkdtemp(join(tmpdir(), 'oce-release-'));
try {
  await mkdir(destination, { recursive: true });
  const { stdout } = await exec('npm', ['pack', '--dry-run', '--json', '--ignore-scripts']);
  const [plan] = JSON.parse(stdout);
  for (const { path } of plan.files) {
    const target = join(stage, path);
    await mkdir(dirname(target), { recursive: true });
    await copyFile(path, target);
  }
  const manifest = JSON.parse(await readFile(join(stage, 'package.json'), 'utf8'));
  // npm may otherwise select README.zh-CN.md as the package homepage.
  manifest.readme = await readFile('README.md', 'utf8');
  manifest.readmeFilename = 'README.md';
  await writeFile(join(stage, 'package.json'), JSON.stringify(manifest, null, 2) + '\n');
  const packed = await exec('npm', ['pack', '--json', '--ignore-scripts', '--pack-destination', destination], { cwd: stage });
  process.stdout.write(packed.stdout);
} finally {
  await rm(stage, { recursive: true, force: true });
}

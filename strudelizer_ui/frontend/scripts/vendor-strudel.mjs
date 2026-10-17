// Copy the pinned Strudel REPL bundle into public/, so the app serves it itself
// and works offline (apart from Strudel's sample loading).
//
// It has to be a plain file rather than a bundler import: dist/index.js resolves
// its clock worker against document.currentScript, so index.js and assets/ must
// stay side by side under a URL we control.
import { cp, mkdir, readFile, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, '../node_modules/@strudel/repl/dist');
const target = resolve(here, '../public/strudel');
const pkg = resolve(here, '../node_modules/@strudel/repl/package.json');

try {
  const { version } = JSON.parse(await readFile(pkg, 'utf8'));
  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });
  await cp(resolve(source, 'index.js'), resolve(target, 'index.js'));
  await cp(resolve(source, 'assets'), resolve(target, 'assets'), { recursive: true });
  console.log(`vendored @strudel/repl@${version} into public/strudel`);
} catch (error) {
  console.error('could not vendor @strudel/repl: run `npm install` first');
  console.error(error.message);
  process.exitCode = 1;
}

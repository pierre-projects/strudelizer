// Copy the pinned Strudel REPL bundle into public/, so the app serves it itself
// and works offline (apart from Strudel's sample loading).
//
// It has to be a plain file rather than a bundler import: dist/index.js resolves
// its clock worker against document.currentScript, so index.js and assets/ must
// stay side by side under a URL we control.
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, '../node_modules/@strudel/repl/dist');
const target = resolve(here, '../public/strudel');
const pkg = resolve(here, '../node_modules/@strudel/repl/package.json');

// 1.2.6 loads its sample indexes from a GitHub path that no longer holds all of
// them (uzu-drumkit.json is gone), and one 404 rejects the whole prebake, so
// nothing plays at all. Strudel itself now loads them from this CDN; the files
// are the same and carry their own `_base`, so only the index host changes.
const DEAD_SAMPLES = 'https://raw.githubusercontent.com/felixroos/dough-samples/main/';
const LIVE_SAMPLES = 'https://strudel.b-cdn.net/';

try {
  const { version } = JSON.parse(await readFile(pkg, 'utf8'));
  await rm(target, { recursive: true, force: true });
  await mkdir(target, { recursive: true });

  const bundle = await readFile(resolve(source, 'index.js'), 'utf8');
  const parts = bundle.split(DEAD_SAMPLES);
  if (parts.length === 1 && !bundle.includes(LIVE_SAMPLES)) {
    throw new Error(`@strudel/repl@${version} no longer references ${DEAD_SAMPLES}; drop this patch`);
  }
  await writeFile(resolve(target, 'index.js'), parts.join(LIVE_SAMPLES));
  await cp(resolve(source, 'assets'), resolve(target, 'assets'), { recursive: true });

  const patched = parts.length - 1;
  console.log(`vendored @strudel/repl@${version} into public/strudel (sample host patched x${patched})`);
} catch (error) {
  console.error('could not vendor @strudel/repl: run `npm install` first');
  console.error(error.message);
  process.exitCode = 1;
}

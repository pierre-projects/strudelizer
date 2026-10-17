// Evaluate generated Strudel files with the pinned Strudel runtime and print
// the events of the first cycles as JSON (one object per input file).
//
//   node validate.mjs [--cycles 4] file.js [file.js ...]
//
// Exit code is 1 if any file fails to evaluate or yields no events.
import { register } from 'node:module';
import { readFileSync } from 'node:fs';

register('./esm-fix.mjs', import.meta.url);

// Strudel logs banners and hints with console.log; keep stdout for our JSON.
console.log = console.info = (...args) => console.error(...args);

const core = await import('@strudel/core');
const mini = await import('@strudel/mini');
const tonal = await import('@strudel/tonal');
const { evaluate } = await import('@strudel/transpiler');

await core.evalScope(core, mini, tonal);

// strudel.cc's REPL provides these; outside the browser we record them instead.
let cps = null;
globalThis.setcps = (value) => {
  cps = value;
};
globalThis.setCps = globalThis.setcps;
globalThis.samples = async () => {};

const args = process.argv.slice(2);
let cycles = 4;
const files = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--cycles') cycles = Number(args[++i]);
  else files.push(args[i]);
}

function midi(value) {
  if (typeof value === 'number') return value;
  try {
    return core.noteToMidi(value);
  } catch {
    return null;
  }
}

const results = [];
let failed = false;
for (const file of files) {
  cps = null;
  const result = { file, ok: false, cps: null, events: [], error: null };
  try {
    const code = readFileSync(file, 'utf8');
    const { pattern } = await evaluate(code);
    if (!pattern || typeof pattern.queryArc !== 'function') {
      throw new Error('the code does not end in a pattern expression');
    }
    const haps = pattern.queryArc(0, cycles).filter((hap) => hap.hasOnset());
    result.events = haps
      .map((hap) => {
        const v = typeof hap.value === 'object' ? hap.value : { value: hap.value };
        const event = {
          start: hap.whole.begin.toFraction(),
          end: hap.whole.end.toFraction(),
        };
        if (v.note !== undefined) event.note = midi(v.note);
        if (v.s !== undefined) event.s = v.s;
        if (v.bank !== undefined) event.bank = v.bank;
        if (v.velocity !== undefined) event.velocity = v.velocity;
        return event;
      })
      .sort((a, b) => {
        const ka = JSON.stringify([core.Fraction(a.start).valueOf(), a.note ?? -1, a.s ?? '']);
        const kb = JSON.stringify([core.Fraction(b.start).valueOf(), b.note ?? -1, b.s ?? '']);
        return ka < kb ? -1 : ka > kb ? 1 : 0;
      });
    result.cps = cps;
    if (result.events.length === 0) throw new Error('the pattern has no events in the first cycles');
    result.ok = true;
  } catch (err) {
    result.error = String(err && err.stack ? err.stack : err);
    failed = true;
  }
  results.push(result);
}

// Exit only once stdout has flushed: on Linux and macOS a pipe is
// asynchronous, and exiting straight after write() cuts the output at the
// 64 KB pipe buffer (Windows pipes are synchronous, so it never shows there).
process.stdout.write(JSON.stringify(results, null, 1) + '\n', () => process.exit(failed ? 1 : 0));

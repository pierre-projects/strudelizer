// Reading the IR for the song view: where the bar lines fall, what is in each
// bar, and which line of the generated code a bar belongs to.
import type { Frac, IrEvent, IrTrack, Song } from './types';

export function frac(value: Frac | undefined | null): number {
  if (!value) return 0;
  const slash = value.indexOf('/');
  if (slash === -1) return Number(value);
  return Number(value.slice(0, slash)) / Number(value.slice(slash + 1));
}

/** In the IR a beat is the time signature's own beat, so 6/8 has six. */
export function beatsPerBar(song: Song): number {
  return song.meta.time_signature ? song.meta.time_signature[0] : 4;
}

/**
 * Silence to imagine before time 0 so bar lines land on bar multiples: with a
 * 2-beat pickup in 4/4 the pickup fills the end of bar 0 and bar 1 follows.
 */
export function barOffset(song: Song): number {
  const pickup = frac(song.meta.pickup_beats);
  return pickup ? beatsPerBar(song) - pickup : 0;
}

export function barOf(song: Song, beat: number): number {
  return Math.floor((beat + barOffset(song)) / beatsPerBar(song));
}

export function eventEnd(event: IrEvent): number {
  return frac(event.start) + (event.type === 'hit' ? 0 : frac(event.duration));
}

export function barCount(song: Song): number {
  let bars = 0;
  for (const section of song.sections) bars = Math.max(bars, section.start_bar + section.length);
  for (const track of song.tracks) {
    bars = Math.max(bars, track.bars?.length ?? 0);
    for (const event of track.events) {
      const end = eventEnd(event) - 1e-9;
      bars = Math.max(bars, barOf(song, Math.max(frac(event.start), end)) + 1);
    }
  }
  return bars;
}

/**
 * What Strudelizer calls this bar in a warning: with a pickup, cycle 0 is the
 * pickup bar and bar 1 is cycle 1; without one, cycle 0 is bar 1.
 */
export function barLabel(song: Song, index: number): string {
  if (barOffset(song)) return index === 0 ? 'pickup' : String(index);
  return String(index + 1);
}

/** The bar index a "bar N" location in a message points at. */
export function barIndex(song: Song, label: number): number {
  return barOffset(song) ? label : label - 1;
}

/** The chord symbol sounding at the start of each bar, for the chord row. */
export function chordRow(song: Song, bars: number): (string | null)[] {
  const row: (string | null)[] = Array(bars).fill(null);
  for (const track of song.tracks) {
    for (const event of track.events) {
      if (event.type !== 'chord') continue;
      const bar = barOf(song, frac(event.start));
      if (bar >= 0 && bar < bars && !row[bar]) row[bar] = event.symbol;
    }
  }
  return row;
}

export function pitchRange(track: IrTrack): [number, number] {
  let low = Infinity;
  let high = -Infinity;
  for (const event of track.events) {
    const pitches = event.type === 'note' ? [event.pitch] : event.type === 'chord' ? event.pitches ?? [] : [];
    for (const pitch of pitches) {
      low = Math.min(low, pitch);
      high = Math.max(high, pitch);
    }
  }
  if (low > high) return [60, 72];
  // Always show at least an octave, so a one-note track is not a full-height block.
  const pad = Math.max(0, 12 - (high - low)) / 2;
  return [low - pad, high + pad];
}

/** The drums this track uses, in the order a kit is usually listed. */
export function drumRows(track: IrTrack): string[] {
  const seen = new Set<string>();
  for (const event of track.events) if (event.type === 'hit') seen.add(event.drum);
  return [...seen].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

const DRUM_ORDER = ['crash', 'ride', 'oh', 'hh', 'tom_hi', 'tom_mid', 'tom_low', 'clap', 'rim', 'snare', 'sd', 'kick', 'bd'];

function rank(drum: string): number {
  const index = DRUM_ORDER.indexOf(drum);
  return index === -1 ? DRUM_ORDER.length / 2 : index;
}

export function trackLabel(track: IrTrack, index: number): string {
  return track.id || `track${index + 1}`;
}

// ---- finding the code a bar came from ---------------------------------------

/**
 * The 1-based line of the generated code that holds a bar: the section's
 * `const`, narrowed to the line inside a multi-line pattern when the section
 * spans several. Null when the code does not say, e.g. a song with no sections.
 */
export function locateBar(code: string, song: Song, bar: number): number | null {
  const section = song.sections.find((s) => bar >= s.start_bar && bar < s.start_bar + s.length);
  if (!section?.name) return null;
  const lines = code.split('\n');
  const declared = new RegExp(`^const ${section.name}(_part|_\\d+)? = `);
  const start = lines.findIndex((line) => declared.test(line));
  if (start === -1) return null;
  const inner = patternLines(lines, start);
  if (!inner) return start + 1;
  const perLine = Math.ceil(section.length / (inner.end - inner.start + 1));
  const offset = Math.min(Math.floor((bar - section.start_bar) / perLine), inner.end - inner.start);
  return inner.start + offset + 1;
}

/** The lines inside the first multi-line `<...>` pattern of a const, if any. */
function patternLines(lines: string[], start: number): { start: number; end: number } | null {
  for (let i = start; i < lines.length; i += 1) {
    if (lines[i] === '') return null;
    if (!lines[i].endsWith('`<')) continue;
    for (let j = i + 1; j < lines.length; j += 1) {
      if (lines[j].trim().startsWith('>`')) return j > i + 1 ? { start: i + 1, end: j - 1 } : null;
    }
  }
  return null;
}

/** The 1-based line of a track's `// id (role)` comment. */
export function locateTrack(code: string, track: IrTrack, index: number): number | null {
  const label = `// ${trackLabel(track, index)} (${track.role || 'other'})`;
  const at = code.split('\n').findIndex((line) => line.trim() === label);
  return at === -1 ? null : at + 2;  // the pattern itself, just below the comment
}

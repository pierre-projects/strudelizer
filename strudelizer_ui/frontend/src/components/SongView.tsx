// A read-only look at the song the way a musician reads a chart: sections over
// a bar ruler, the chord in each bar, and one lane per track. Clicking a bar or
// a track scrolls the generated code to the line it came from.
import { useEffect, useRef, useState } from 'preact/hooks';
import {
  barCount,
  barLabel,
  barOf,
  beatsPerBar,
  chordRow,
  drumRows,
  frac,
  locateBar,
  locateTrack,
  pitchRange,
  trackLabel,
} from '../song';
import type { Store } from '../state';
import type { IrTrack, Song } from '../types';

const MIN_BAR = 46;  // px per bar; a long song scrolls sideways past the panel
const LANE = 54;

export function SongView({ store }: { store: Store }) {
  const song = store.processed ?? store.song;
  if (!song) return null;
  const bars = barCount(song);
  if (!bars) return null;

  return (
    <section class="panel" aria-labelledby="arrangement-heading">
      <header>
        <h2 id="arrangement-heading">Arrangement</h2>
        <span class="small muted">
          {bars} bars · {song.meta.bpm ?? '?'} BPM · {(song.meta.time_signature ?? [4, 4]).join('/')}
          {song.meta.key ? ` · ${song.meta.key}` : ''}
        </span>
      </header>
      <Chart store={store} song={song} bars={bars} />
    </section>
  );
}

function Chart({ store, song, bars }: { store: Store; song: Song; bars: number }) {
  const chords = chordRow(song, bars);
  const sections = filled(song, bars);
  const code = store.effectiveCode;
  // A short song spreads across the panel; a long one keeps its minimum.
  const wrap = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState(0);
  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setRoom(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const BAR = Math.max(MIN_BAR, Math.floor(room / bars) || MIN_BAR);

  const goToBar = (bar: number) => {
    const line = locateBar(code, song, bar);
    if (line) store.reveal(line);
  };

  return (
    <div class="body songview" ref={wrap}>
        <div class="chart" style={`--bar:${BAR}px;--bars:${bars}`}>
          {sections.length > 0 && (
            <div class="lane sections" role="list" aria-label="Sections">
              {sections.map((section) => (
                <div
                  key={`${section.name}-${section.start_bar}`}
                  role="listitem"
                  class="section"
                  style={`grid-column:${section.start_bar + 1} / span ${section.length}`}
                  title={`${section.name ?? 'part'}: ${section.length} bar(s) from ${barLabel(song, section.start_bar)}`}
                >
                  {section.name ?? 'part'}
                </div>
              ))}
            </div>
          )}

          <div class="lane ruler">
            {range(bars).map((bar) => (
              <button
                key={bar}
                type="button"
                class="bar"
                title={`Show bar ${barLabel(song, bar)} in the code`}
                onClick={() => goToBar(bar)}
              >
                {barLabel(song, bar)}
              </button>
            ))}
          </div>

          {chords.some(Boolean) && (
            <div class="lane chords" aria-label="Chords">
              {chords.map((symbol, bar) => (
                <span key={bar} class="bar" title={symbol ? `Bar ${barLabel(song, bar)}: ${symbol}` : undefined}>
                  {symbol ?? ''}
                </span>
              ))}
            </div>
          )}
        </div>

        <ul class="tracks">
          {song.tracks.map((track, index) => {
            const id = track.id ?? `track_${index}`;
            const silent = !store.playing.includes(id);
            return (
              <li key={id} class={silent ? 'off' : ''}>
                <div class="track-head">
                  <span class="track-name" title={`${trackLabel(track, index)} (${track.role ?? 'other'})${
                    track.instrument ? ` on ${track.instrument}` : ''
                  }`}>
                    {trackLabel(track, index)}
                    <span class="muted"> {track.role ?? 'other'}</span>
                  </span>
                  <span class="row">
                    <button
                      type="button"
                      class="tiny"
                      aria-pressed={store.muted.includes(id)}
                      title={`Leave ${trackLabel(track, index)} out of the code`}
                      onClick={() => store.toggleMute(id)}
                    >
                      Mute
                    </button>
                    <button
                      type="button"
                      class="tiny"
                      aria-pressed={store.soloed.includes(id)}
                      title={`Generate only ${trackLabel(track, index)}`}
                      onClick={() => store.toggleSolo(id)}
                    >
                      Solo
                    </button>
                  </span>
                </div>
                <div
                  class="lane-wrap"
                  style={`--bar:${BAR}px;--bars:${bars}`}
                  onClick={() => {
                    const line = locateTrack(code, track, index);
                    if (line) store.reveal(line);
                  }}
                >
                  <TrackLane song={song} track={track} bars={bars} bar={BAR} label={trackLabel(track, index)} />
                </div>
              </li>
            );
          })}
        </ul>
    </div>
  );
}

/** A drum grid for a drum track, a piano roll for anything with pitches. */
function TrackLane({
  song,
  track,
  bars,
  bar: BAR,
  label,
}: {
  song: Song;
  track: IrTrack;
  bars: number;
  bar: number;
  label: string;
}) {
  const width = bars * BAR;
  const beats = beatsPerBar(song);
  const offset = frac(song.meta.pickup_beats) ? beats - frac(song.meta.pickup_beats) : 0;
  const x = (beat: number) => ((beat + offset) / beats) * BAR;
  const drums = drumRows(track);
  const rows = drums.length;
  const height = rows ? Math.max(LANE, rows * 11) : LANE;
  const [low, high] = pitchRange(track);
  const span = Math.max(1, high - low);

  return (
    <svg
      class="lane-art"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${label}: ${rows ? 'drum grid' : 'notes'}`}
    >
      {range(bars).map((bar) => (
        <line key={bar} class="barline" x1={bar * BAR} x2={bar * BAR} y1={0} y2={height} />
      ))}
      {rows > 0
        ? track.events.map((event, i) => {
            if (event.type !== 'hit') return null;
            const row = drums.indexOf(event.drum);
            const y = ((row + 0.5) / rows) * height;
            return (
              <circle
                key={i}
                class="hit"
                cx={x(frac(event.start))}
                cy={y}
                r={3.2}
                opacity={0.45 + 0.55 * ((event.velocity ?? 100) / 127)}
              >
                <title>{`${event.drum} in bar ${barLabel(song, barOf(song, frac(event.start)))}`}</title>
              </circle>
            );
          })
        : notes(track).map(([start, duration, pitch, velocity], i) => {
            const y = height - 5 - ((pitch - low) / span) * (height - 10);
            return (
              <rect
                key={i}
                class="note"
                x={x(start)}
                y={y}
                width={Math.max(2, (duration / beats) * BAR - 1)}
                height={4}
                rx={2}
                opacity={0.5 + 0.5 * (velocity / 127)}
              >
                <title>{`bar ${barLabel(song, barOf(song, start))}`}</title>
              </rect>
            );
          })}
    </svg>
  );
}

/** [start, duration, pitch, velocity] for notes and for each chord tone. */
function notes(track: IrTrack): [number, number, number, number][] {
  const out: [number, number, number, number][] = [];
  for (const event of track.events) {
    if (event.type === 'note') {
      out.push([frac(event.start), frac(event.duration), event.pitch, event.velocity ?? 100]);
    } else if (event.type === 'chord') {
      // A chord carries no velocity, so every tone is drawn the same.
      for (const pitch of event.pitches ?? []) out.push([frac(event.start), frac(event.duration), pitch, 90]);
    }
  }
  return out;
}

/** Sections with the gaps filled, the way arrange() covers the song. */
function filled(song: Song, bars: number) {
  if (song.sections.length === 0) return [];
  const out: { name?: string; start_bar: number; length: number }[] = [];
  let at = 0;
  for (const section of [...song.sections].sort((a, b) => a.start_bar - b.start_bar)) {
    if (section.start_bar > at) out.push({ start_bar: at, length: section.start_bar - at });
    out.push(section);
    at = section.start_bar + section.length;
  }
  if (at < bars) out.push({ start_bar: at, length: bars - at });
  return out;
}

function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i);
}

"""arrange pass (FR-23): generate missing drums and bass from a style.

    arrange:lofi          (CLI: --style lofi)
    arrange:style=my.yaml

Only parts the song lacks are generated: a drums track if there is none,
a bass track if there is none and the song has chord symbols to follow.
If the style gives a chord rhythm, chords are re-struck on it. When a bass
part plays (generated or not), slash chords are voiced without their slash
note, which the bass plays instead.

Generated parts cover full bars only; a pickup bar keeps just its chords.
"""

from __future__ import annotations

import bisect
from dataclasses import replace
from fractions import Fraction
from typing import Any, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.ir import Chord, Hit, Note, Song, Track
from ..core.theory import CHORD_ROOT_OCTAVE_BASE, ChordSpelling, parse_chord, pitch_class
from ..core.time import bar_offset, beats_per_bar, song_length_bars, time_signature
from ..registry import Pass, get_style

STAGE = "pass:arrange"


def _spelling(chord: Chord) -> ChordSpelling | None:
    if chord.root is not None and chord.quality is not None:
        return ChordSpelling(chord.root, chord.quality, tuple(chord.extensions or ()), chord.bass)
    return parse_chord(chord.symbol)


def _unique_id(base: str, used: set[str]) -> str:
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


class Arrange(Pass):
    """Generate missing drums and bass from a style template (lofi, rock, four_on_floor)."""

    name = "arrange"
    default_option = "style"

    def run(self, song: Song, options: Mapping[str, Any]) -> Song:
        style_name = options.get("style")
        if not style_name:
            raise StrudelizerError(STAGE, "no style given", fix="e.g. arrange:lofi or --style lofi")
        style = get_style(str(style_name))
        num, den = time_signature(song.meta)
        meter = f"{num}/{den}"
        spec = style["meters"].get(meter)
        if spec is None:
            raise StrudelizerError(
                STAGE,
                f"style '{style['name']}' has no patterns for {meter}",
                location=f"style {style_name}",
                fix=f"the style covers {', '.join(style['meters'])}; add a \"{meter}\" entry to a copy of it",
            )
        return _Arranger(song, style, spec).run()


class _Arranger:
    def __init__(self, song: Song, style: Mapping[str, Any], spec: Mapping[str, Any]) -> None:
        self.song = song
        self.style = style
        self.spec = spec
        self.bar_len = beats_per_bar(song.meta)
        self.offset = bar_offset(song.meta)
        self.n_bars = song_length_bars(song)
        self.step = self.bar_len / spec["steps"]
        first = 1 if self.offset else 0  # generated parts skip the pickup bar
        self.bar_starts = [b * self.bar_len - self.offset for b in range(first, self.n_bars)]
        velocity = style["velocity"]
        self.velocity = {"X": velocity["accent"], "x": velocity["normal"], "g": velocity["ghost"]}
        chords = [
            e for t in song.tracks if t.role == "chords" for e in t.events if isinstance(e, Chord)
        ] or [e for t in song.tracks for e in t.events if isinstance(e, Chord)]
        self.chords = sorted(chords, key=lambda c: c.start)
        self.chord_starts = [c.start for c in self.chords]

    def times(self, pattern: str) -> list[tuple[Fraction, str]]:
        return [
            (start + i * self.step, char)
            for start in self.bar_starts
            for i, char in enumerate(pattern)
            if char != "."
        ]

    def chord_at(self, t: Fraction) -> Chord | None:
        i = bisect.bisect_right(self.chord_starts, t) - 1
        if i >= 0 and t < self.chords[i].start + self.chords[i].duration:
            return self.chords[i]
        return None

    def run(self) -> Song:
        tracks = list(self.song.tracks)
        used = {t.id for t in tracks if t.id}
        name = self.style["name"]
        has_drums = any(t.role == "drums" and t.events for t in tracks)
        has_bass = any(t.role == "bass" and t.events for t in tracks)

        if not has_drums and self.spec["drums"] and self.bar_starts:
            hits = [
                Hit(t, drum, self.velocity[char])
                for drum, pattern in self.spec["drums"].items()
                for t, char in self.times(pattern)
            ]
            tracks.append(Track(events=tuple(hits), id=_unique_id("drums", used), role="drums", instrument=f"style:{name}"))

        if not has_bass and self.spec["bass"]:
            if not self.chords:
                warn(STAGE, "the song has no chord symbols to follow, so no bass part was generated")
            else:
                notes = self.bass()
                if notes:
                    tracks.append(Track(events=tuple(notes), id=_unique_id("bass", used), role="bass", instrument=f"style:{name}"))
                    has_bass = True

        tracks = [self.chord_track(t, revoice=has_bass) if any(isinstance(e, Chord) for e in t.events) else t for t in tracks]
        return replace(self.song, tracks=tuple(tracks))

    # ---- bass ----------------------------------------------------------------------

    def bass(self) -> list[Note]:
        hits = dict((t, self.velocity[c]) for t, c in self.times(self.spec["bass"]))
        first_bar = self.bar_starts[0] if self.bar_starts else Fraction(0)
        for chord in self.chords:  # follow every chord change, on the rhythm or not
            if chord.start >= first_bar:
                hits.setdefault(chord.start, self.velocity["x"])
        times = sorted(hits)
        rule = self.style["bass"]["rule"]
        low_base = (self.style["bass"]["octave"] + 1) * 12
        notes: list[Note] = []
        previous: Chord | None = None
        count = 0
        for i, t in enumerate(times):
            chord = self.chord_at(t)
            spelling = _spelling(chord) if chord is not None else None
            if spelling is None:
                previous = None
                continue
            count = count + 1 if chord is previous else 0
            previous = chord
            end = chord.start + chord.duration
            if i + 1 < len(times):
                end = min(end, times[i + 1])
            bass_pc = pitch_class(spelling.bass or spelling.root)
            low = low_base + bass_pc
            pitch = low
            if count % 2 == 1:
                if rule == "root_fifth":
                    intervals = [p - (CHORD_ROOT_OCTAVE_BASE + pitch_class(spelling.root)) for p in spelling.pitches(with_bass=False)]
                    fifth = next((i for i in (7, 6, 8) if i in intervals), 7)
                    pitch = low + (pitch_class(spelling.root) + fifth - bass_pc) % 12
                elif rule == "root_octave":
                    pitch = low + 12
            notes.append(Note(t, end - t, pitch, hits[t]))
        return notes

    # ---- chords ----------------------------------------------------------------------

    def chord_track(self, track: Track, revoice: bool) -> Track:
        strikes = [t for t, _ in self.times(self.spec["chords"])] if self.spec["chords"] else []
        events = []
        changed = False
        for event in track.events:
            if not isinstance(event, Chord):
                events.append(event)
                continue
            if revoice and event.bass is not None:
                spelling = _spelling(event)
                if spelling is not None:
                    upper = spelling.pitches(with_bass=False)
                    bass_pc = pitch_class(spelling.bass)
                    without = tuple(p for p in upper if p % 12 != bass_pc)
                    event = replace(event, pitches=without if len(without) >= 2 else upper)
                    changed = True
            end = event.start + event.duration
            inside = [t for t in strikes if event.start < t < end]
            if not inside:
                events.append(event)
                continue
            changed = True
            points = [event.start] + inside + [end]
            for a, b in zip(points, points[1:]):
                events.append(replace(event, start=a, duration=b - a))
        return replace(track, events=tuple(events), bars=None) if changed else track

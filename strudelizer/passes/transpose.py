"""transpose pass (FR-24): shift everything pitched by N semitones.

    transpose:2      transpose:-3      transpose:semitones=5

Notes and chord pitches move; chord roots, slash bass notes, symbols and
meta.key are respelled in the new key (flats for flat keys). Drum hits are
unchanged. A uniform shift keeps identical bars identical, so `bars` from
dedupe_bars stays valid.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.ir import Chord, Note, Song, Track
from ..core.theory import format_key, key_prefers_flats, parse_key, split_symbol, transpose_note
from ..core.time import bar_offset, beats_per_bar
from ..registry import Pass

STAGE = "pass:transpose"


class Transpose(Pass):
    """Shift notes, chords and the key by N semitones (transpose:-2)."""

    name = "transpose"
    default_option = "semitones"

    def run(self, song: Song, options: Mapping[str, Any]) -> Song:
        raw = options.get("semitones", 0)
        try:
            n = int(str(raw).replace("+", "", 1))
        except ValueError:
            raise StrudelizerError(
                STAGE, f"semitones must be a whole number, not {raw!r}",
                location="option semitones", fix="e.g. transpose:-2 or transpose:5",
            ) from None
        if n == 0:
            return song
        key = song.meta.key
        new_key = key
        if key:
            parsed = parse_key(key)
            if parsed is None:
                warn(STAGE, f"cannot read key {key!r}; left it unchanged")
            else:
                new_key = format_key((parsed[0] + n) % 12, parsed[1])
        flats = key_prefers_flats(new_key) if new_key else None
        self._song = song
        tracks = tuple(self._track(t, n, flats) for t in song.tracks)
        return replace(song, meta=replace(song.meta, key=new_key), tracks=tracks)

    def _where(self, track: Track, start) -> str:
        bar_len = beats_per_bar(self._song.meta)
        index = math.floor((start + bar_offset(self._song.meta)) / bar_len)
        bar = index if bar_offset(self._song.meta) else index + 1
        return f"track {track.id or '?'}, bar {bar}"

    def _pitch(self, pitch: int, n: int, track: Track, start) -> int:
        new = pitch + n
        if not 0 <= new <= 127:
            raise StrudelizerError(
                STAGE, f"pitch {pitch} transposed by {n} leaves the MIDI range 0-127",
                location=self._where(track, start), fix="transpose by fewer semitones, or by an octave less",
            )
        return new

    def _track(self, track: Track, n: int, flats: bool | None) -> Track:
        events = []
        for e in track.events:
            if isinstance(e, Note):
                e = replace(e, pitch=self._pitch(e.pitch, n, track, e.start))
            elif isinstance(e, Chord):
                e = self._chord(e, n, flats, track)
            events.append(e)
        return replace(track, events=tuple(events))

    def _chord(self, chord: Chord, n: int, flats: bool | None, track: Track) -> Chord:
        def move(note: str | None) -> str | None:
            if note is None:
                return None
            use_flats = flats if flats is not None else ("b" in note)
            return transpose_note(note, n, use_flats)

        parts = split_symbol(chord.symbol)
        root = move(chord.root) if chord.root else (move(parts[0]) if parts else None)
        bass = move(chord.bass) if chord.bass else (move(parts[2]) if parts and parts[2] else None)
        if parts is not None and root is not None:
            symbol = root + parts[1] + (f"/{bass}" if bass else "")
        else:
            symbol = chord.symbol
        pitches = tuple(self._pitch(p, n, track, chord.start) for p in chord.pitches) if chord.pitches else chord.pitches
        return replace(
            chord,
            symbol=symbol,
            root=root if chord.root else chord.root,
            bass=bass if chord.bass else chord.bass,
            pitches=pitches,
        )

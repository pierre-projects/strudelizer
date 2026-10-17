"""MIDI emitter (FR-32): write the IR as a Standard MIDI File.

Type 1, 480 ticks per quarter note. A conductor track holds the title,
tempo, time signature and key. Each IR track becomes one MIDI track named
after its id: notes and chords on its own channel (GM program from the
`gm:N` instrument hint, else a default per role), drum hits on GM channel
10. A pickup is written the way notation programs write it, as a short
first bar (e.g. 1/4 before 4/4), which the MIDI importer reads back.
"""

from __future__ import annotations

import io
import math
from fractions import Fraction
from typing import Any, Mapping

from ..core.errors import warn
from ..core.ir import Hit, Note, Song
from ..core.theory import chord_pitches
from ..core.time import DEFAULT_BPM, time_signature
from ..registry import Emitter

STAGE = "emit:midi"
TPQ = 480
DRUM_CHANNEL = 9
HIT_TICKS = TPQ // 8  # drum hits sound for a 32nd note

# IR drum -> General MIDI key; the MIDI importer maps each back to the same name.
GM_KEYS = {
    "kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46, "clap": 39, "rim": 37,
    "tom_low": 43, "tom_mid": 47, "tom_high": 50, "crash": 49, "ride": 51,
    "cowbell": 56, "tambourine": 54, "shaker": 70,
}
ROLE_PROGRAMS = {"bass": 33, "chords": 0, "melody": 73, "vocal": 52, "other": 0, "drums": 0}
MELODIC_CHANNELS = [c for c in range(16) if c != DRUM_CHANNEL]


class MidiEmitter(Emitter):
    """Standard MIDI file (.mid), type 1, drums on GM channel 10."""

    name = "midi"
    extension = ".mid"
    binary = True

    def emit(self, song: Song, options: Mapping[str, Any]) -> bytes:
        import mido

        meta = song.meta
        num, den = time_signature(meta)
        scale = Fraction(TPQ * 4, den)  # ticks per IR beat
        inexact = 0

        def ticks(beats: Fraction) -> int:
            nonlocal inexact
            exact = beats * scale
            if exact.denominator != 1:
                inexact += 1
            return math.floor(exact + Fraction(1, 2))

        mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)

        bpm = meta.bpm if meta.bpm is not None else DEFAULT_BPM
        conductor: list[tuple[int, int, Any]] = [
            (0, 0, mido.MetaMessage("set_tempo", tempo=round(60_000_000 / (bpm * 4 / den)))),
        ]
        pickup = meta.pickup_beats
        if pickup:
            k = pickup.denominator
            if k & (k - 1) == 0 and den * k <= 64:  # representable as n/2^m
                conductor.append((0, 1, mido.MetaMessage("time_signature", numerator=int(pickup * k), denominator=den * k)))
                conductor.append((ticks(pickup), 1, mido.MetaMessage("time_signature", numerator=num, denominator=den)))
            else:
                warn(STAGE, f"a {pickup}-beat pickup cannot be written as a MIDI time signature; wrote {num}/{den} only")
                pickup = None
        if not pickup:
            conductor.append((0, 1, mido.MetaMessage("time_signature", numerator=num, denominator=den)))
        if meta.key:
            try:
                conductor.append((0, 2, mido.MetaMessage("key_signature", key=meta.key)))
            except (ValueError, KeyError):
                warn(STAGE, f"key {meta.key!r} has no MIDI key signature; left it out")
        mid.tracks.append(_track(meta.title or "Strudelizer", conductor))

        channels = iter(MELODIC_CHANNELS * 16)
        skipped = 0
        for index, track in enumerate(song.tracks):
            if not track.events:
                continue
            messages: list[tuple[int, int, Any]] = []
            has_pitched = any(not isinstance(e, Hit) for e in track.events)
            channel = next(channels) if has_pitched else None
            if channel is not None:
                program = ROLE_PROGRAMS.get(track.role or "other", 0)
                if track.instrument and track.instrument.startswith("gm:") and track.instrument[3:].isdigit():
                    program = min(int(track.instrument[3:]), 127)
                messages.append((0, 0, mido.Message("program_change", channel=channel, program=program)))
            for e in track.events:
                start = ticks(e.start)
                if isinstance(e, Hit):
                    _note(messages, DRUM_CHANNEL, GM_KEYS[e.drum], start, start + HIT_TICKS, e.velocity)
                    continue
                if isinstance(e, Note):
                    pitches: tuple[int, ...] = (e.pitch,)
                else:  # Chord
                    pitches = e.pitches or ()
                    if not pitches and e.root and e.quality:
                        try:
                            pitches = chord_pitches(e.root, e.quality, e.extensions, e.bass)
                        except ValueError:
                            pitches = ()
                    if not pitches:
                        skipped += 1
                        continue
                end = max(ticks(e.start + e.duration), start + 1)
                for pitch in pitches:
                    _note(messages, channel, pitch, start, end, getattr(e, "velocity", None))
            mid.tracks.append(_track(track.id or f"track{index + 1}", messages))

        if skipped:
            warn(STAGE, f"{skipped} chord(s) without pitches or a known quality were left out")
        if inexact:
            warn(STAGE, f"{inexact} time(s) are not whole MIDI ticks at {TPQ} per quarter and were rounded")
        buffer = io.BytesIO()
        mid.save(file=buffer)
        return buffer.getvalue()


def _note(messages: list, channel: int, pitch: int, start: int, end: int, velocity: int | None) -> None:
    import mido

    # order key 1 = note-off, 2 = note-on: at equal ticks, offs come first
    messages.append((start, 2, mido.Message("note_on", channel=channel, note=pitch, velocity=velocity or 100)))
    messages.append((end, 1, mido.Message("note_off", channel=channel, note=pitch, velocity=0)))


def _track(name: str, messages: list[tuple[int, int, Any]]):
    import mido

    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    now = 0
    ordered = sorted(
        messages,
        key=lambda m: (m[0], m[1], getattr(m[2], "channel", -1), getattr(m[2], "note", -1)),
    )
    for tick, _, msg in ordered:
        track.append(msg.copy(time=tick - now))
        now = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track

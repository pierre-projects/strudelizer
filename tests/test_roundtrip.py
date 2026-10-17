"""MIDI -> IR -> MIDI -> IR round trip, compared note by note with the
source after quantize (PRD success metric: 98%+).

The source side is read with mido directly and snapped by the small,
independent quantizer below, so an importer or emitter bug cannot hide
itself.
"""

import math
from collections import Counter
from fractions import Fraction as F

import mido
import pytest
from conftest import FIXTURES, MIDI_FIXTURES

from strudelizer import Pipeline
from strudelizer.core import Hit

TARGET = 0.98
GM = {36: "kick", 38: "snare", 39: "clap", 42: "closed_hat", 46: "open_hat", 49: "crash",
      54: "tambourine", 56: "cowbell", 70: "shaker"}


def source_notes(path, grid=("16", "8t")):
    mid = mido.MidiFile(str(path))
    den = 4
    for track in mid.tracks:
        for msg in track:
            if msg.type == "time_signature":
                den = msg.denominator
    steps = []
    for g in grid:
        step = F(den, int(g.rstrip("t")))
        steps.append(step * F(2, 3) if g.endswith("t") else step)

    def snap(beats):
        best = None
        for step in steps:
            point = math.floor(beats / step + F(1, 2)) * step
            key = (abs(beats - point), point, step)
            best = key if best is None or key[:2] < best[:2] else best
        return best[1], best[2]

    def beats(tick):
        return F(tick, mid.ticks_per_beat) * F(den, 4)

    per_part = {}
    for t_index, track in enumerate(mid.tracks):
        tick, held = 0, {}
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity:
                held.setdefault((msg.channel, msg.note), []).append(tick)
            elif msg.type in ("note_on", "note_off"):
                start = held[(msg.channel, msg.note)].pop(0)
                s, step = snap(beats(start))
                if msg.channel == 9:
                    key = ("hit", GM[msg.note], s)
                else:
                    e, _ = snap(beats(tick))
                    key = ("note", msg.note, s, max(e - s, step))
                per_part.setdefault((t_index, msg.channel), Counter())[key] += 1
    return [per_part[k] for k in sorted(per_part)]


def ir_notes(song):
    parts = []
    for track in song.tracks:
        c = Counter()
        for e in track.events:
            c[("hit", e.drum, e.start) if isinstance(e, Hit) else ("note", e.pitch, e.start, e.duration)] += 1
        parts.append(c)
    return parts


def _ratio(expected, actual):
    assert len(expected) == len(actual)
    total = sum(sum(c.values()) for c in expected)
    matched = sum(sum((e & a).values()) for e, a in zip(expected, actual))
    extra = sum(sum(a.values()) for a in actual) - matched
    return matched, total, extra, matched / max(total, matched + extra)


@pytest.mark.parametrize("name", MIDI_FIXTURES)
def test_round_trip_through_midi_emitter(name, tmp_path):
    source = FIXTURES / f"{name}.mid"
    first = Pipeline(passes="quantize:16+8t", emitter="midi").run(source)
    written = tmp_path / f"{name}.out.mid"
    written.write_bytes(first)
    again = Pipeline(passes=None).load(written)
    matched, total, extra, ratio = _ratio(source_notes(source), ir_notes(again))
    assert ratio >= TARGET, f"{name}: {matched}/{total} notes match ({ratio:.1%}), {extra} extra"
    original = Pipeline(passes=None).load(source)
    assert again.meta.bpm == original.meta.bpm
    assert again.meta.time_signature == original.meta.time_signature
    assert again.meta.pickup_beats == original.meta.pickup_beats
    assert again.meta.key == original.meta.key
    assert [(t.id, t.role) for t in again.tracks] == [(t.id, t.role) for t in original.tracks]


@pytest.mark.parametrize("name", MIDI_FIXTURES)
def test_round_trip_fidelity(name):
    song = Pipeline(passes="quantize:16+8t").transform(Pipeline(passes=None).load(FIXTURES / f"{name}.mid"))
    expected = source_notes(FIXTURES / f"{name}.mid")
    actual = ir_notes(song)
    assert len(expected) == len(actual)
    total = sum(sum(c.values()) for c in expected)
    matched = sum(sum((e & a).values()) for e, a in zip(expected, actual))
    extra = sum(sum(a.values()) for a in actual) - matched
    ratio = matched / max(total, matched + extra)
    assert ratio >= TARGET, f"{name}: {matched}/{total} notes match ({ratio:.1%}), {extra} extra"


# ---- P3 gate: tab / Guitar Pro / MusicXML -> IR -> MIDI -> IR -------------------

from conftest import golden_base, notation_params  # noqa: E402

from strudelizer.core import Chord as _Chord  # noqa: E402


def _content(song):
    """Per track: multiset of (pitch or drum, start, duration) after expanding
    chords to their pitches, plus the multiset of pitches alone."""
    parts = []
    for track in song.tracks:
        events, pitches = Counter(), Counter()
        for e in track.events:
            if isinstance(e, Hit):
                events[("hit", e.drum, e.start)] += 1
            elif isinstance(e, _Chord):
                for p in e.pitches or ():
                    events[("note", p, e.start, e.duration)] += 1
                    pitches[p] += 1
            else:
                events[("note", e.pitch, e.start, e.duration)] += 1
                pitches[e.pitch] += 1
        parts.append((events, pitches))
    return parts


@pytest.mark.filterwarnings("ignore::strudelizer.StrudelizerWarning")
@pytest.mark.parametrize("rel,options", notation_params())
def test_notation_round_trip_through_midi(rel, options, tmp_path):
    pipeline = Pipeline(passes="quantize:16+8t", importer_options=options)
    source = pipeline.transform(pipeline.load(FIXTURES / rel))
    midi = tmp_path / (golden_base(rel).name + ".mid")
    midi.write_bytes(Pipeline(passes=None, emitter="midi").emit(source))
    again = Pipeline(passes=None).load(midi)
    before, after = _content(source), _content(again)
    assert len(before) == len(after), [t.id for t in again.tracks]
    for (b_events, b_pitches), (a_events, a_pitches), track in zip(before, after, source.tracks):
        assert a_pitches == b_pitches, f"{rel} track {track.id}: pitches differ"
        total = sum(b_events.values())
        matched = sum((b_events & a_events).values())
        assert matched / max(total, sum(a_events.values())) >= TARGET, f"{rel} track {track.id}: {matched}/{total}"

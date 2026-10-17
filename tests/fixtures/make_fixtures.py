"""Generate the MIDI test fixtures with mido (nothing is downloaded).

    python tests/fixtures/make_fixtures.py

Output is deterministic; tests/test_golden.py checks that running this
reproduces the checked-in .mid files byte for byte.
"""

from __future__ import annotations

import io
from pathlib import Path

import mido

HERE = Path(__file__).parent
TPQ = 480  # ticks per quarter note
Q = TPQ
E = TPQ // 2  # eighth
S = TPQ // 4  # sixteenth
T8 = TPQ // 3  # eighth-note triplet

DRUM_CH = 9
GM = {"kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46, "crash": 49, "clap": 39}


def _track(name: str, notes, channel: int = 0, program: int | None = None, meta=()) -> mido.MidiTrack:
    """notes: (start_tick, duration_tick, pitch, velocity)."""
    events = []  # (tick, order, message); note_off sorts before note_on
    for tick, msg in meta:
        events.append((tick, -1, msg))
    for start, dur, pitch, vel in notes:
        events.append((start, 1, mido.Message("note_on", channel=channel, note=pitch, velocity=vel)))
        events.append((start + dur, 0, mido.Message("note_off", channel=channel, note=pitch, velocity=0)))
    events.sort(key=lambda e: (e[0], e[1], getattr(e[2], "note", -1)))
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    if program is not None:
        track.append(mido.Message("program_change", channel=channel, program=program, time=0))
    now = 0
    for tick, _, msg in events:
        track.append(msg.copy(time=tick - now))
        now = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def _conductor(title: str, bpm: float, num: int = 4, den: int = 4, key: str | None = None) -> mido.MidiTrack:
    meta = [
        (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))),
        (0, mido.MetaMessage("time_signature", numerator=num, denominator=den)),
    ]
    if key:
        meta.append((0, mido.MetaMessage("key_signature", key=key)))
    return _track(title, [], meta=meta)


def _drums(bars: list[list[tuple[int, str, int]]], bar_ticks: int):
    """bars: per bar, (tick_in_bar, drum, velocity)."""
    out = []
    for i, bar in enumerate(bars):
        for tick, drum, vel in bar:
            out.append((i * bar_ticks + tick, S // 2, GM[drum], vel))
    return out


def _seq(bars: list[list[tuple[int, int, int]]], bar_ticks: int, vel: int = 96):
    """bars: per bar, (tick_in_bar, duration, pitch)."""
    return [(i * bar_ticks + t, d, p, vel) for i, bar in enumerate(bars) for t, d, p in bar]


def _file(*tracks: mido.MidiTrack) -> mido.MidiFile:
    mid = mido.MidiFile(type=1, ticks_per_beat=TPQ)
    mid.tracks.extend(tracks)
    return mid


# ---- fixtures -------------------------------------------------------------------


def drums_44() -> mido.MidiFile:
    bar = 4 * Q
    hats = [(i * E, "closed_hat", 100 if i % 2 == 0 else 70) for i in range(8)]
    a = [(0, "kick", 110), (2 * Q, "kick", 110), (Q, "snare", 100), (3 * Q, "snare", 100)] + hats
    b = (
        [(0, "kick", 110), (Q + E, "kick", 90), (2 * Q, "kick", 110), (Q, "snare", 100), (3 * Q, "snare", 100)]
        + hats[:7]
        + [(7 * E, "open_hat", 90)]
    )
    first = a + [(0, "crash", 120)]
    return _file(_conductor("Drums 4/4", 120), _track("Drums", _drums([first, b, a, b], bar), channel=DRUM_CH))


def bassline() -> mido.MidiFile:
    bar = 4 * Q
    c2, eb2, f2, g2, bb1, c3 = 36, 39, 41, 43, 34, 48
    bars = [
        [(0, Q + E, c2), (Q + E, E, c2), (2 * Q, Q, eb2), (3 * Q, Q, g2)],
        [(0, E, f2), (E, E, f2), (Q, Q, c3), (2 * Q, Q, bb1), (3 * Q, Q + 2 * Q, g2)],  # ties into bar 3
        [(2 * Q, E, f2), (2 * Q + E, E, eb2), (3 * Q, Q, c2)],
        [(0, 2 * Q, c2), (2 * Q, S, g2), (2 * Q + S, S, f2), (2 * Q + 2 * S, E, eb2), (3 * Q, Q, c2)],
    ]
    return _file(_conductor("Bassline", 100, key="Cm"), _track("Bass", _seq(bars, bar), program=33))


# Small deterministic timing errors, in ticks, so quantize has work to do.
JITTER = [0, 6, -5, 9, -8, 4, -3, 7, -9, 2, 5, -6, 8, -4, 3, -7]


def melody_triplets() -> mido.MidiFile:
    bar = 4 * Q
    e4, g4, a4, b4, c5, d5 = 64, 67, 69, 71, 72, 74
    bars = [
        # beat 1-2: eighth-note triplets; beat 3: quarter; beat 4: two eighths
        [(0, T8, e4), (T8, T8, g4), (2 * T8, T8, a4), (Q, T8, b4), (Q + T8, T8, a4), (Q + 2 * T8, T8, g4),
         (2 * Q, Q, e4), (3 * Q, E, d5), (3 * Q + E, E, c5)],
        [(0, Q, b4), (Q, T8, a4), (Q + T8, T8, b4), (Q + 2 * T8, T8, c5), (2 * Q, 2 * Q, e4)],
    ]
    notes = []
    for i, (start, dur, pitch, vel) in enumerate(_seq(bars, bar, vel=88)):
        j = JITTER[i % len(JITTER)]
        notes.append((max(0, start + j), dur - abs(j) // 2, pitch, vel))
    return _file(_conductor("Triplet Melody", 90), _track("Lead", notes, program=73))


def multitrack_repeats() -> mido.MidiFile:
    bar = 4 * Q
    groove = [(i * Q, "kick", 110) for i in range(4)] + [(Q, "snare", 100), (3 * Q, "snare", 100)]
    groove += [(i * E, "closed_hat", 80) for i in range(8)]
    fill = [(i * Q, "kick", 110) for i in range(3)] + [(Q, "snare", 100)]
    fill += [(i * E, "closed_hat", 80) for i in range(6)]
    fill += [(3 * Q + i * S, "snare", 100) for i in range(4)]
    drums = _drums([groove] * 7 + [fill], bar)

    a2, f2, c3, g2, e2 = 45, 41, 48, 43, 40
    b1 = [(0, E, a2), (E, E, a2), (Q, Q, c3), (2 * Q, E, a2), (2 * Q + E, E, a2), (3 * Q, Q, e2)]
    b2 = [(0, Q, f2), (Q, Q, f2), (2 * Q, Q, g2), (3 * Q, Q, g2)]
    bass = _seq([b1, b1, b2, b2, b1, b1, b2, b2], bar)

    am, fmaj, cmaj, gmaj = (57, 60, 64), (53, 57, 60), (55, 60, 64), (55, 59, 62)
    chord_bars = [[(0, 2 * Q, p) for p in ch] + [(2 * Q, 2 * Q, p) for p in ch] for ch in (am, fmaj, cmaj, gmaj)]
    chords = _seq(chord_bars * 2, bar, vel=72)

    m1 = [(0, Q, 76), (Q, E, 74), (Q + E, E, 72), (2 * Q, 2 * Q, 69)]
    m2 = [(0, E, 72), (E, E, 74), (Q, Q, 76), (2 * Q, Q, 77), (3 * Q, Q, 76)]
    m3 = [(0, 4 * Q, 74)]
    melody = _seq([m1, m2, m1, m3, m1, m2, m1, m3], bar, vel=100)

    return _file(
        _conductor("Repeats", 124, key="Am"),
        _track("Drums", drums, channel=DRUM_CH),
        _track("Bass", bass, channel=1, program=38),
        _track("Keys", chords, channel=2, program=4),
        _track("Lead", melody, channel=3, program=80),
    )


def groove_78() -> mido.MidiFile:
    bar = 7 * E  # 7/8
    pat = [(0, "kick", 110), (2 * E, "snare", 100), (4 * E, "kick", 110), (5 * E, "snare", 100)]
    pat += [(i * E, "closed_hat", 80) for i in range(7)]
    d2, f2, a2, c3 = 38, 41, 45, 48
    b1 = [(0, Q, d2), (2 * E, E, f2), (4 * E, E, a2), (5 * E, Q, c3)]
    b2 = [(0, Q, d2), (2 * E, E, d2), (4 * E, Q + E, a2)]
    return _file(
        _conductor("Groove in 7/8", 70, num=7, den=8, key="Dm"),
        _track("Kit", _drums([pat] * 4, bar), channel=DRUM_CH),
        _track("Synth Bass", _seq([b1, b2, b1, b2], bar), channel=1, program=38),
    )


def pickup_percussion() -> mido.MidiFile:
    """A one-beat pickup (written, as notation programs do, as a 1/4 bar
    before the 4/4 meter) plus cowbell, tambourine and shaker."""
    pickup = Q
    bar = 4 * Q
    conductor = _track(
        "Pickup Percussion",
        [],
        meta=[
            (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(110))),
            (0, mido.MetaMessage("time_signature", numerator=1, denominator=4)),
            (pickup, mido.MetaMessage("time_signature", numerator=4, denominator=4)),
        ],
    )
    # melody: two eighth-note pickup notes, then two bars
    g4, a4, b4, c5, d5, e5 = 67, 69, 71, 72, 74, 76
    lead = [(0, E, g4, 90), (E, E, a4, 90)]
    lead += [(pickup + t, d, p, 96) for t, d, p in [(0, Q, b4), (Q, Q, c5), (2 * Q, 2 * Q, d5)]]
    lead += [(pickup + bar + t, d, p, 96) for t, d, p in [(0, 2 * Q, e5), (2 * Q, 2 * Q, c5)]]
    perc = []
    for b in range(2):
        start = pickup + b * bar
        perc += [(start + i * E, S // 2, 70, 80) for i in range(8)]  # maracas -> shaker
        perc += [(start + Q, S // 2, 54, 90), (start + 3 * Q, S // 2, 54, 90)]  # tambourine
        perc += [(start, S // 2, 56, 100), (start + 2 * Q + E, S // 2, 56, 100)]  # cowbell
        perc += [(start, S // 2, 36, 110), (start + 2 * Q, S // 2, 36, 110)]  # kick
    perc.append((E, S // 2, 38, 80))  # a snare pickup hit on the "and"
    return _file(
        conductor,
        _track("Lead", lead, channel=0, program=73),
        _track("Percussion", perc, channel=DRUM_CH),
    )


FIXTURES = {
    "drums_44": drums_44,
    "bassline": bassline,
    "melody_triplets": melody_triplets,
    "multitrack_repeats": multitrack_repeats,
    "groove_78": groove_78,
    "pickup_percussion": pickup_percussion,
}


def build_all() -> dict[str, bytes]:
    out = {}
    for name, make in FIXTURES.items():
        buf = io.BytesIO()
        make().save(file=buf)
        out[name] = buf.getvalue()
    return out


def main() -> None:
    for name, data in build_all().items():
        (HERE / f"{name}.mid").write_bytes(data)
        print(f"wrote {name}.mid ({len(data)} bytes)")


if __name__ == "__main__":
    main()

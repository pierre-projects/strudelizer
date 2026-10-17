"""Generate the Guitar Pro fixtures with PyGuitarPro (nothing is downloaded).

    python tests/fixtures/make_gp_fixtures.py

`gp/song.gp5`: an original 4-track song. Covers drop-D tuning (rhythm
guitar), a capo (lead, capo 3), a 4-string bass, a percussion track, ties
across bar lines, a triplet, a grace note and a dead note (both dropped), a
repeat with first and second endings, and section markers.

Measures (written):  1 |: 2  3 |1. 4 :|2. 5 | 6
Played (unfolded):   1  2  3  4  2  3  5  6
"""

from __future__ import annotations

import io
from pathlib import Path

import guitarpro as gp

HERE = Path(__file__).parent / "gp"
QUARTER = gp.Duration.quarterTime  # 960 ticks
BAR = 4 * QUARTER

DROP_D = [(1, 64), (2, 59), (3, 55), (4, 50), (5, 45), (6, 38)]
STANDARD = [(1, 64), (2, 59), (3, 55), (4, 50), (5, 45), (6, 40)]
BASS = [(1, 43), (2, 38), (3, 33), (4, 28)]
DRUMS = [(n, 0) for n in range(1, 7)]


def _duration(value: int, dotted: bool = False, triplet: bool = False) -> gp.Duration:
    tuplet = gp.Tuplet(3, 2) if triplet else gp.Tuplet()
    return gp.Duration(value=value, isDotted=dotted, tuplet=tuplet)


def _beat(voice, value: int, notes=(), *, dotted=False, triplet=False, rest=False):
    """notes: (string, fret, type, extras) tuples."""
    beat = gp.Beat(voice, duration=_duration(value, dotted, triplet),
                   status=gp.BeatStatus.rest if rest else gp.BeatStatus.normal)
    for string, fret, kind, *extra in notes:
        note = gp.Note(beat, value=fret, string=string, type=kind, velocity=gp.Velocities.forte)
        if "grace" in extra:
            note.effect = gp.NoteEffect(grace=gp.GraceEffect(fret=fret, duration=32))
        beat.notes.append(note)
    voice.beats.append(beat)


N, TIE, DEAD = gp.NoteType.normal, gp.NoteType.tie, gp.NoteType.dead


def _fill(track, bars: list[list[tuple]]) -> None:
    """bars[i] = list of (value, notes, flags) beats for measure i."""
    for measure, beats in zip(track.measures, bars):
        voice = measure.voices[0]
        for value, notes, *flags in beats:
            _beat(voice, value, notes, dotted="dotted" in flags, triplet="triplet" in flags, rest="rest" in flags)


def song() -> gp.Song:
    s = gp.Song()
    s.title = "Harbor Steps"
    s.artist = "Strudelizer test suite (original)"
    s.tempo = 112
    s.measureHeaders = []
    for i in range(6):
        header = gp.MeasureHeader(number=i + 1, start=QUARTER + i * BAR,
                                  timeSignature=gp.TimeSignature(4, gp.Duration(4)))
        s.measureHeaders.append(header)
    h = s.measureHeaders
    h[0].marker = gp.Marker(title="Intro")
    h[1].isRepeatOpen = True
    h[1].marker = gp.Marker(title="Verse")
    h[3].repeatAlternative = 0b01  # 1st ending
    h[3].repeatClose = 1  # jump back once
    h[4].repeatAlternative = 0b10  # 2nd ending
    h[5].marker = gp.Marker(title="Outro")
    s.tracks = []

    def track(number, name, strings, channel, program, capo=0, percussion=False):
        t = gp.Track(s, number=number, name=name, strings=[gp.GuitarString(n, v) for n, v in strings],
                     offset=capo, isPercussionTrack=percussion,
                     channel=gp.MidiChannel(channel=channel, effectChannel=channel, instrument=program))
        s.tracks.append(t)
        return t

    rhythm = track(1, "Rhythm Guitar", DROP_D, 0, 29)
    power = lambda fret: [(6, fret, N), (5, fret, N), (4, fret, N)]  # noqa: E731  drop-D one-finger power chord
    _fill(rhythm, [
        [(8, power(0)), (8, power(0)), (8, power(3)), (8, power(0)), (4, power(5)), (4, power(3))],
        [(8, power(0)), (8, power(0)), (8, [(6, 0, DEAD)]), (8, power(0)), (2, power(7))],
        [(4, power(5)), (4, power(3)), (2, power(0))],
        [(1, power(10))],
        [(2, power(12)), (2, power(10))],
        [(1, power(0))],
    ])

    lead = track(2, "Lead", STANDARD, 1, 27, capo=3)
    _fill(lead, [
        [(1, [], "rest")],
        [(4, [(2, 5, N)]), (8, [(2, 7, N)]), (8, [(2, 8, N)]), (2, [(1, 5, N)])],
        # tied across the bar line from measure 2, then a triplet
        [(4, [(1, 5, TIE)]), (8, [(1, 3, N)], "triplet"), (8, [(1, 5, N)], "triplet"),
         (8, [(1, 7, N)], "triplet"), (2, [(2, 8, N)])],
        # a grace note (fret 7) before the dotted half: an effect on that note
        [(2, [(2, 8, N, "grace")], "dotted"), (8, [(2, 7, N)]), (8, [(2, 5, N)])],
        [(1, [(1, 3, N)])],
        [(2, [(1, 3, TIE)]), (2, [], "rest")],  # outro note tied from the 2nd ending
    ])

    bass = track(3, "Bass", BASS, 2, 33)
    _fill(bass, [
        [(4, [(4, 2, N)]), (4, [(4, 2, N)]), (4, [(4, 5, N)]), (4, [(4, 7, N)])],
        [(4, [(4, 2, N)]), (4, [(3, 0, N)]), (4, [(3, 2, N)]), (4, [(4, 5, N)])],
        [(2, [(4, 7, N)]), (2, [(3, 0, N)])],
        [(1, [(3, 3, N)])],
        [(2, [(3, 5, N)]), (2, [(3, 3, N)])],
        [(1, [(4, 2, N)])],
    ])

    drums = track(4, "Drums", DRUMS, 9, 0, percussion=True)
    kick, snare, hat, crash = 36, 38, 42, 49
    groove = [(8, [(1, kick, N), (2, hat, N)]), (8, [(2, hat, N)]), (8, [(1, snare, N), (2, hat, N)]), (8, [(2, hat, N)])] * 2
    _fill(drums, [
        [(8, [(1, kick, N), (2, crash, N)])] + groove[1:],
        groove, groove, groove, groove,
        [(1, [(1, kick, N), (2, crash, N)])],
    ])
    return s


FIXTURES = {"song": song}


def build_all() -> dict[str, bytes]:
    out = {}
    for name, make in FIXTURES.items():
        buffer = io.BytesIO()
        gp.write(make(), buffer, version=(5, 1, 0))
        out[name] = buffer.getvalue()
    return out


def main() -> None:
    HERE.mkdir(exist_ok=True)
    for name, data in build_all().items():
        (HERE / f"{name}.gp5").write_bytes(data)
        print(f"wrote gp/{name}.gp5 ({len(data)} bytes)")


if __name__ == "__main__":
    main()

import io
from fractions import Fraction as F

import mido
import pytest
from conftest import FIXTURES, SHEETS

from strudelizer import Pipeline
from strudelizer.cli import main
from strudelizer.core import Chord, Hit, Meta, Note, Song, StrudelizerWarning, Track
from strudelizer.emitters.midi import GM_KEYS, MidiEmitter
from strudelizer.importers.midi import GM_DRUMS, MidiImporter


def parse(data: bytes) -> mido.MidiFile:
    return mido.MidiFile(file=io.BytesIO(data))


def test_every_drum_maps_back_to_itself():
    for drum, key in GM_KEYS.items():
        assert GM_DRUMS[key] == drum


def test_conductor_and_channels():
    song = Song(
        meta=Meta(title="T", bpm=140, time_signature=(7, 8), key="Dm"),
        tracks=(
            Track(id="bass", role="bass", instrument="gm:38", events=(Note(F(0), F(2), 38, 90),)),
            Track(id="kit", role="drums", events=(Hit(F(1), "cowbell", 70),)),
        ),
    )
    mid = parse(MidiEmitter().emit(song, {}))
    assert mid.type == 1 and mid.ticks_per_beat == 480
    meta = {m.type: m for m in mid.tracks[0]}
    assert meta["set_tempo"].tempo == mido.bpm2tempo(70)  # 140 eighths = 70 quarters
    assert (meta["time_signature"].numerator, meta["time_signature"].denominator) == (7, 8)
    assert meta["key_signature"].key == "Dm"
    bass = [m for m in mid.tracks[1] if not m.is_meta]
    assert bass[0].type == "program_change" and bass[0].program == 38
    assert (bass[1].note, bass[1].velocity, bass[1].channel) == (38, 90, 0)
    assert bass[2].time == 480  # 2 eighth notes
    kit = [m for m in mid.tracks[2] if m.type == "note_on"]
    assert (kit[0].channel, kit[0].note) == (9, 56)


def test_chords_become_notes():
    song = Song(tracks=(Track(id="c", role="chords", events=(
        Chord(F(0), F(4), "C/E", root="C", quality="maj", bass="E", pitches=(40, 48, 52, 55)),
        Chord(F(4), F(4), "G7", root="G", quality="7"),  # no pitches: voiced from the quality
    )),))
    mid = parse(MidiEmitter().emit(song, {}))
    notes = [m.note for m in mid.tracks[1] if m.type == "note_on"]
    assert notes == [40, 48, 52, 55, 55, 59, 62, 65]


def test_pickup_written_as_short_first_bar_and_read_back(tmp_path):
    song = Pipeline(passes=None).load(FIXTURES / "pickup_percussion.mid")
    path = tmp_path / "out.mid"
    path.write_bytes(MidiEmitter().emit(song, {}))
    signatures = [(m.numerator, m.denominator, m.time) for m in parse(path.read_bytes()).tracks[0] if m.type == "time_signature"]
    assert signatures == [(1, 4, 0), (4, 4, 480)]
    assert MidiImporter().load(path, {}).meta.pickup_beats == F(1)


def test_inexact_times_are_rounded_with_a_warning():
    song = Song(tracks=(Track(events=(Note(F(1, 7), F(1), 60),)),))
    with pytest.warns(StrudelizerWarning, match="rounded"):
        MidiEmitter().emit(song, {})


def test_deterministic_and_cli(tmp_path):
    a = Pipeline(emitter="midi").run(FIXTURES / "multitrack_repeats.mid")
    b = Pipeline(emitter="midi").run(FIXTURES / "multitrack_repeats.mid")
    assert a == b and isinstance(a, bytes)
    out = tmp_path / "song.mid"
    assert main([str(SHEETS / "night_train.txt"), "--bpm", "90", "--style", "rock", "-o", str(out)]) == 0
    roles = [t.role for t in MidiImporter().load(out, {}).tracks]
    assert roles == ["chords", "drums", "bass"]

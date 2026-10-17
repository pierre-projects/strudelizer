from fractions import Fraction as F
from pathlib import Path

import mido
import pytest

from strudelizer.core import Hit, Note, StrudelizerError, StrudelizerWarning
from strudelizer.importers.midi import MidiImporter

FIXTURES = Path(__file__).parent / "fixtures"


def load(path):
    song = MidiImporter().load(path, {})
    song.validate()
    return song


def write(tmp_path, *tracks, tpq=480, name="t.mid"):
    mid = mido.MidiFile(type=1, ticks_per_beat=tpq)
    for msgs in tracks:
        tr = mido.MidiTrack()
        tr.extend(msgs)
        mid.tracks.append(tr)
    path = tmp_path / name
    mid.save(str(path))
    return path


def on(note, t=0, ch=0, vel=100):
    return mido.Message("note_on", note=note, velocity=vel, channel=ch, time=t)


def off(note, t=0, ch=0):
    return mido.Message("note_off", note=note, velocity=0, channel=ch, time=t)


def test_drum_channel_maps_to_vocabulary():
    song = load(FIXTURES / "drums_44.mid")
    (drums,) = song.tracks
    assert drums.role == "drums"
    assert {e.drum for e in drums.events} == {"kick", "snare", "closed_hat", "open_hat", "crash"}
    assert all(isinstance(e, Hit) for e in drums.events)
    assert drums.events[0] == Hit(F(0), "kick", 110)


def test_seven_eight_uses_eighth_note_beats():
    song = load(FIXTURES / "groove_78.mid")
    assert song.meta.time_signature == (7, 8)
    assert song.meta.bpm == 140
    kit = song.tracks[0]
    snares = [e.start for e in kit.events if e.drum == "snare"]
    assert snares[:2] == [F(2), F(5)]  # eighth notes 3 and 6 of bar 1
    assert snares[2] == F(9)  # bar 2 starts at beat 7


def test_meta_and_roles():
    song = load(FIXTURES / "multitrack_repeats.mid")
    assert song.meta.title == "Repeats"
    assert song.meta.key == "Am"
    assert song.meta.source == "multitrack_repeats.mid"
    assert [(t.id, t.role) for t in song.tracks] == [
        ("drums", "drums"),
        ("bass", "bass"),
        ("keys", "chords"),
        ("lead", "melody"),
    ]


def test_note_pairing_velocity_zero_and_unclosed(tmp_path):
    path = write(
        tmp_path,
        [
            mido.MetaMessage("track_name", name="Synth"),
            on(60), on(60, 240),  # overlapping same pitch: FIFO pairing
            mido.Message("note_on", note=60, velocity=0, time=240),
            off(60, 240),
            on(64, 0),  # never released
            mido.MetaMessage("end_of_track", time=480),
        ],
    )
    (track,) = load(path).tracks
    assert track.events == (
        Note(F(0), F(1), 60, 100),
        Note(F(1, 2), F(1), 60, 100),
        Note(F(3, 2), F(1), 64, 100),
    )


def test_tempo_change_warns_and_uses_dominant(tmp_path):
    path = write(
        tmp_path,
        [
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(90)),
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=480 * 4),
            mido.MetaMessage("end_of_track", time=480 * 12),
        ],
        [on(60), off(60, 480)],
    )
    with pytest.warns(StrudelizerWarning, match="tempo changes") as rec:
        song = load(path)
    assert song.meta.bpm == 120
    assert rec[0].message.stage == "import:midi"


def test_meter_change_warns(tmp_path):
    path = write(
        tmp_path,
        [
            mido.MetaMessage("time_signature", numerator=3, denominator=4),
            mido.MetaMessage("time_signature", numerator=4, denominator=4, time=480 * 6),
            mido.MetaMessage("end_of_track", time=480 * 16),
        ],
        [on(60), off(60, 480)],
    )
    with pytest.warns(StrudelizerWarning, match="time signature changes"):
        song = load(path)
    assert song.meta.time_signature == (4, 4)


def test_unmapped_gm_drum_dropped_with_warning(tmp_path):
    path = write(tmp_path, [on(58, ch=9), off(58, 60, ch=9), on(36, ch=9), off(36, 60, ch=9)])
    with pytest.warns(StrudelizerWarning, match="58 x1"):
        song = load(path)
    assert [e.drum for e in song.tracks[0].events] == ["kick"]


def test_defaults_without_meta(tmp_path):
    path = write(tmp_path, [on(60), off(60, 480)], name="plain.mid")
    song = load(path)
    assert song.meta.bpm == 120
    assert song.meta.time_signature == (4, 4)
    assert song.meta.title == "plain"


def test_bad_file_reports_stage_and_location(tmp_path):
    bad = tmp_path / "broken.mid"
    bad.write_bytes(b"MThd garbage")
    with pytest.raises(StrudelizerError) as info:
        MidiImporter().load(bad, {})
    assert info.value.stage == "import:midi"
    assert "broken.mid" in info.value.location
    assert info.value.fix

    with pytest.raises(StrudelizerError, match="file not found"):
        MidiImporter().load(tmp_path / "missing.mid", {})


def test_can_handle():
    imp = MidiImporter()
    assert imp.can_handle("x.MID")
    assert imp.can_handle(FIXTURES / "bassline.mid")
    assert not imp.can_handle("x.txt")

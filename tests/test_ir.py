from fractions import Fraction as F

import pytest

from strudelizer.core import Chord, Hit, Meta, Note, Section, Song, StrudelizerError, Track
from strudelizer.core.ir import load_schema, validate_dict
from strudelizer.core.theory import midi_to_name, name_to_midi
from strudelizer.core.time import format_frac, parse_frac, slice_bars, song_length_bars


def sample_song() -> Song:
    return Song(
        meta=Meta(title="t", bpm=120, time_signature=(4, 4), key="C"),
        sections=(Section(start_bar=0, length=2, name="verse"),),
        tracks=(
            Track(
                id="lead",
                role="melody",
                events=(Note(F(1, 3), F(1, 3), 64, 90), Note(F(0), F(1, 3), 60)),
            ),
            Track(id="drums", role="drums", events=(Hit(F(0), "kick", 100), Hit(F(1), "snare"))),
            Track(
                id="keys",
                role="chords",
                events=(Chord(F(0), F(4), "Cmaj7", root="C", quality="maj7", pitches=(60, 64, 67, 71)),),
            ),
        ),
    )


def test_fraction_format_roundtrip():
    for value in [F(0), F(3), F(1, 3), F(7, 2)]:
        assert parse_frac(format_frac(value)) == value
    assert format_frac(F(2, 4)) == "1/2"
    assert format_frac(F(4, 2)) == "2"


def test_dict_and_json_roundtrip():
    song = sample_song()
    data = song.to_dict()
    validate_dict(data)
    again = Song.from_dict(data)
    assert again == song
    assert Song.from_json(song.to_json()) == song
    # events are sorted on construction, so the 1/3 note comes second
    assert data["tracks"][0]["events"][0]["start"] == "0"
    assert data["tracks"][0]["events"][1]["start"] == "1/3"


def test_json_is_stable():
    assert sample_song().to_json() == sample_song().to_json()
    assert sample_song().to_json().endswith("\n")


def test_only_events_required():
    validate_dict({"tracks": [{"events": []}]})
    song = Song.from_dict({"tracks": [{"events": [{"type": "note", "start": "0", "duration": "1", "pitch": 60}]}]})
    assert song.meta == Meta()


@pytest.mark.parametrize(
    "bad,where",
    [
        ({"tracks": [{"events": [{"type": "note", "start": "0.5", "duration": "1", "pitch": 60}]}]}, "start"),
        ({"tracks": [{"events": [{"type": "note", "start": "0", "duration": "0", "pitch": 60}]}]}, "duration"),
        ({"tracks": [{"events": [{"type": "hit", "start": "0", "drum": "agogo"}]}]}, "drum"),
        ({"tracks": [{"role": "lead", "events": []}]}, "role"),
        ({"tracks": [{"events": [{"type": "boom", "start": "0"}]}]}, "type"),
        ({"meta": {"time_signature": [7, 7]}, "tracks": []}, "time_signature"),
        ({}, "(document root)"),
    ],
)
def test_schema_rejects(bad, where):
    with pytest.raises(StrudelizerError) as info:
        validate_dict(bad, stage="test")
    assert info.value.stage == "test"
    assert where in info.value.location


def test_schema_is_published_and_versioned():
    schema = load_schema()
    assert schema["properties"]["version"] == {"const": "2"}


def test_slice_bars_splits_across_barline():
    track = Track(events=(Note(F(3), F(2), 60), Hit(F(4), "kick")))
    bars = slice_bars(track.events, F(4), 2)
    assert bars[0] == (Note(F(3), F(1), 60),)
    assert bars[1] == (Hit(F(0), "kick"), Note(F(0), F(1), 60))


def test_song_length_bars():
    song = Song(tracks=(Track(events=(Hit(F(8), "kick"),)),))
    assert song_length_bars(song) == 3
    song = Song(tracks=(Track(events=(Note(F(0), F(8), 60),)),))
    assert song_length_bars(song) == 2


def test_note_names():
    assert midi_to_name(60) == "c4"
    assert midi_to_name(61) == "c#4"
    assert midi_to_name(21) == "a0"
    for p in range(0, 128):
        assert name_to_midi(midi_to_name(p)) == p
    assert name_to_midi("Eb3") == 51

from fractions import Fraction as F
from pathlib import Path

import pytest

from strudelizer.core import Hit, Meta, Note, Song, StrudelizerError, Track
from strudelizer.importers.midi import MidiImporter
from strudelizer.passes.quantize import Quantize, parse_grid, snap

FIXTURES = Path(__file__).parent / "fixtures"


def song(*events, ts=(4, 4), bars=None):
    return Song(meta=Meta(time_signature=ts), tracks=(Track(events=events, bars=bars),))


def test_parse_grid_units():
    assert parse_grid("16", 4) == [F(1, 4)]
    assert parse_grid(8, 4) == [F(1, 2)]
    assert parse_grid("8t", 4) == [F(1, 3)]
    assert parse_grid("16+8t", 4) == [F(1, 4), F(1, 3)]
    # in 7/8 a beat is an eighth, so a 16th is half a beat
    assert parse_grid("16", 8) == [F(1, 2)]


@pytest.mark.parametrize("bad", ["13", "16x", "", "8++16"])
def test_bad_grid(bad):
    with pytest.raises(StrudelizerError) as info:
        parse_grid(bad, 4)
    assert info.value.stage == "pass:quantize"
    assert "16+8t" in info.value.fix


def test_snap_prefers_nearest_grid():
    steps = parse_grid("16+8t", 4)
    assert snap(F(330, 1000), steps) == (F(1, 3), F(1, 3))
    assert snap(F(26, 100), steps) == (F(1, 4), F(1, 4))
    assert snap(F(0), steps) == (F(0), F(1, 4))


def test_quantize_notes_hits_and_min_duration():
    s = song(
        Note(F(49, 100), F(2, 100), 60, 80),
        Hit(F(101, 100), "kick", 100),
    )
    out = Quantize().run(s, {"grid": "16"})
    assert out.tracks[0].events == (
        Note(F(1, 2), F(1, 4), 60, 80),  # tiny note gets one grid step
        Hit(F(1), "kick", 100),
    )


def test_duplicates_merge_keeping_longest_and_loudest():
    s = song(Note(F(0), F(1), 60, 50), Note(F(1, 100), F(2), 60, 90), Hit(F(0), "kick", 60), Hit(F(1, 50), "kick", 100))
    out = Quantize().run(s, {"grid": "16"})
    assert out.tracks[0].events == (Hit(F(0), "kick", 100), Note(F(0), F(2), 60, 90))


def test_quantize_is_pure_and_clears_bars():
    s = song(Note(F(1, 10), F(1), 60), bars=(0,))
    out = Quantize().run(s, {})
    assert s.tracks[0].events[0].start == F(1, 10)
    assert out.tracks[0].bars is None


def test_triplet_fixture_recovers_triplets():
    s = MidiImporter().load(FIXTURES / "melody_triplets.mid", {})
    out = Quantize().run(s, {"grid": "16+8t"})
    starts = [e.start for e in out.tracks[0].events][:6]
    assert starts == [F(0), F(1, 3), F(2, 3), F(1), F(4, 3), F(5, 3)]
    assert all(e.duration == F(1, 3) for e in out.tracks[0].events[:6])

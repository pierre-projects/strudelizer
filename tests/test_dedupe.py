from fractions import Fraction as F
from pathlib import Path

from strudelizer.core import Hit, Meta, Note, Song, Track
from strudelizer.importers.midi import MidiImporter
from strudelizer.passes.dedupe_bars import DedupeBars
from strudelizer.passes.quantize import Quantize

FIXTURES = Path(__file__).parent / "fixtures"


def test_marks_first_identical_bar():
    kick = [Hit(F(4 * b), "kick") for b in range(4)]
    snare = [Hit(F(4 * b + 2), "snare") for b in (1, 3)]
    song = Song(meta=Meta(time_signature=(4, 4)), tracks=(Track(events=tuple(kick + snare)),))
    out = DedupeBars().run(song, {})
    assert out.tracks[0].bars == (0, 1, 0, 1)
    assert out.tracks[0].events == song.tracks[0].events  # events untouched
    assert song.tracks[0].bars is None  # input not mutated


def test_tied_note_tail_makes_bars_differ():
    # bar 2 holds the tail of a note from bar 1, so it is not equal to bar 3
    song = Song(
        tracks=(
            Track(
                events=(
                    Note(F(0), F(6), 60),
                    Note(F(8), F(2), 60),
                    Note(F(10), F(2), 60),
                )
            ),
        )
    )
    out = DedupeBars().run(song, {})
    assert out.tracks[0].bars == (0, 1, 2)


def test_velocity_counts_as_content():
    song = Song(tracks=(Track(events=(Hit(F(0), "kick", 100), Hit(F(4), "kick", 50))),))
    assert DedupeBars().run(song, {}).tracks[0].bars == (0, 1)


def test_bars_cover_whole_song_for_every_track():
    song = Quantize().run(MidiImporter().load(FIXTURES / "multitrack_repeats.mid", {}), {})
    out = DedupeBars().run(song, {})
    by_id = {t.id: t.bars for t in out.tracks}
    assert by_id["drums"] == (0, 0, 0, 0, 0, 0, 0, 7)
    assert by_id["bass"] == (0, 0, 2, 2, 0, 0, 2, 2)
    assert by_id["keys"] == (0, 1, 2, 3, 0, 1, 2, 3)
    assert by_id["lead"] == (0, 1, 0, 3, 0, 1, 0, 3)
    out.validate()

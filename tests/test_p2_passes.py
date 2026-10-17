"""arrange, detect_sections, transpose, remap_drums."""

from fractions import Fraction as F

import pytest
from conftest import FIXTURES, SHEETS

from strudelizer import Pipeline
from strudelizer.core import Chord, Hit, Meta, Note, Section, Song, StrudelizerError, StrudelizerWarning, Track
from strudelizer.core.theory import parse_chord
from strudelizer.passes.arrange import Arrange
from strudelizer.passes.remap_drums import RemapDrums
from strudelizer.passes.sections import DetectSections
from strudelizer.passes.transpose import Transpose


def chord(start, dur, symbol):
    c = parse_chord(symbol)
    return Chord(F(start), F(dur), symbol, root=c.root, quality=c.quality,
                 extensions=c.extensions or None, bass=c.bass, pitches=c.pitches())


def chord_song(*chords, ts=(4, 4), pickup=None):
    return Song(meta=Meta(time_signature=ts, bpm=90, pickup_beats=pickup),
                tracks=(Track(id="chords", role="chords", events=tuple(chords)),))


# ---- arrange -------------------------------------------------------------------------


def test_arrange_adds_drums_and_bass_from_template():
    song = Arrange().run(chord_song(chord(0, 4, "C"), chord(4, 4, "Am")), {"style": "lofi"})
    roles = {t.role: t for t in song.tracks}
    assert set(roles) == {"chords", "drums", "bass"}
    kicks = [e.start for e in roles["drums"].events if e.drum == "kick"]
    assert kicks == [F(0), F(7, 4), F(5, 2), F(4), F(23, 4), F(13, 2)]  # "x......x..x....." per bar
    bass = [(e.start, e.duration, e.pitch) for e in roles["bass"].events]
    # root_fifth over C then Am, rhythm steps 0, 7, 10
    assert bass == [
        (F(0), F(7, 4), 36), (F(7, 4), F(3, 4), 43), (F(5, 2), F(3, 2), 36),
        (F(4), F(7, 4), 45), (F(23, 4), F(3, 4), 52), (F(13, 2), F(3, 2), 45),
    ]
    assert roles["drums"].instrument == "style:lofi"


def test_slash_chord_bass_plays_slash_note_and_chord_drops_it():
    song = Arrange().run(chord_song(chord(0, 4, "C/E")), {"style": "rock"})
    roles = {t.role: t for t in song.tracks}
    assert {e.pitch % 12 for e in roles["bass"].events} == {4}  # E
    for c in roles["chords"].events:
        assert 4 not in {p % 12 for p in c.pitches}  # voiced without E
        assert c.bass == "E"


def test_arrange_restrikes_chords_and_follows_chord_changes():
    song = Arrange().run(chord_song(chord(0, 3, "C"), chord(3, 1, "G")), {"style": "rock"})
    roles = {t.role: t for t in song.tracks}
    strikes = [(e.start, e.symbol) for e in roles["chords"].events]
    assert strikes == [(F(0), "C"), (F(1), "C"), (F(2), "C"), (F(3), "G")]
    assert [e.pitch for e in roles["bass"].events][-2:] == [43, 43]  # G under the change


def test_arrange_keeps_existing_parts():
    song = chord_song(chord(0, 4, "C"))
    song = Song(meta=song.meta, tracks=song.tracks + (Track(id="kit", role="drums", events=(Hit(F(0), "kick"),)),))
    out = Arrange().run(song, {"style": "lofi"})
    assert [t.id for t in out.tracks] == ["chords", "kit", "bass"]


def test_arrange_skips_pickup_bar():
    song = Arrange().run(chord_song(chord(0, 1, "G"), chord(1, 4, "C"), pickup=F(1)), {"style": "rock"})
    roles = {t.role: t for t in song.tracks}
    assert min(e.start for e in roles["drums"].events) == F(1)
    assert min(e.start for e in roles["bass"].events) == F(1)


def test_arrange_errors():
    with pytest.raises(StrudelizerError, match="no patterns for 7/8") as info:
        Arrange().run(chord_song(chord(0, 7, "C"), ts=(7, 8)), {"style": "lofi"})
    assert "4/4, 3/4" in info.value.fix
    with pytest.raises(StrudelizerError, match="no style named"):
        Arrange().run(chord_song(chord(0, 4, "C")), {"style": "polka"})
    song = Song(meta=Meta(bpm=90), tracks=(Track(id="m", role="melody", events=(Note(F(0), F(4), 60),)),))
    with pytest.warns(StrudelizerWarning, match="no chord symbols"):
        out = Arrange().run(song, {"style": "lofi"})
    assert [t.role for t in out.tracks] == ["melody", "drums"]


def test_style_file(tmp_path):
    path = tmp_path / "mine.yaml"
    path.write_text('name: mine\nbass: {rule: root_octave}\nmeters:\n  "4/4":\n    steps: 4\n'
                    '    drums: {kick: "x.x."}\n    bass: "xxxx"\n')
    out = Arrange().run(chord_song(chord(0, 4, "A")), {"style": str(path)})
    bass = [e.pitch for e in out.tracks[-1].events]
    assert bass == [45, 57, 45, 57]
    path.write_text('meters:\n  "4/4":\n    steps: 4\n    drums: {kick: "x.x"}\n')
    with pytest.raises(StrudelizerError, match="3 steps, the meter says 4"):
        Arrange().run(chord_song(chord(0, 4, "A")), {"style": str(path)})


# ---- detect_sections ------------------------------------------------------------------------


def test_detect_sections_on_midi():
    song = Pipeline(passes="quantize,detect_sections").run(FIXTURES / "multitrack_repeats.mid")
    assert "const part_a" in song and "arrange(" in song
    s = Pipeline(passes="quantize,detect_sections").transform(Pipeline(passes=None).load(FIXTURES / "multitrack_repeats.mid"))
    # the drum fill in bar 8 makes the 4-bar halves differ, so 2-bar blocks win: A B A C
    assert [(x.name, x.start_bar, x.length) for x in s.sections] == [
        ("part_a", 0, 2), ("part_b", 2, 2), ("part_a", 4, 2), ("part_c", 6, 2),
    ]


def test_detect_sections_repeats_get_one_name():
    bars = [60, 62, 60, 62, 64, 64, 60, 62]  # blocks of 2: A A B A
    song = Song(tracks=(Track(events=tuple(Note(F(4 * i), F(4), p) for i, p in enumerate(bars))),))
    out = DetectSections().run(song, {})
    assert [(s.name, s.start_bar, s.length) for s in out.sections] == [
        ("part_a", 0, 2), ("part_a", 2, 2), ("part_b", 4, 2), ("part_a", 6, 2),
    ]


def test_detect_sections_never_overwrites_and_leaves_unique_songs_alone():
    song = Song(sections=(Section(0, 1, "intro"),), tracks=(Track(events=(Note(F(0), F(4), 60),)),))
    assert DetectSections().run(song, {}) is song
    unique = Song(tracks=(Track(events=tuple(Note(F(4 * i), F(4), 60 + i) for i in range(8))),))
    assert DetectSections().run(unique, {}).sections == ()


def test_detect_sections_pickup():
    meta = Meta(pickup_beats=F(1))
    events = (Note(F(0), F(1), 55),) + tuple(Note(F(1 + 4 * i), F(4), 60 + (i % 2)) for i in range(4))
    out = DetectSections().run(Song(meta=meta, tracks=(Track(events=events),)), {"bars": "2"})
    assert [(s.name, s.start_bar, s.length) for s in out.sections] == [
        ("pickup", 0, 1), ("part_a", 1, 2), ("part_a", 3, 2),
    ]


# ---- transpose -----------------------------------------------------------------------------


def test_transpose_moves_notes_chords_and_key():
    song = Song(
        meta=Meta(key="F"),
        tracks=(
            Track(id="c", events=(chord(0, 4, "Fmaj7/A"), chord(4, 4, "Bb6/9"))),
            Track(id="m", events=(Note(F(0), F(1), 60), Hit(F(0), "kick"))),
        ),
    )
    up = Transpose().run(song, {"semitones": "2"})
    assert up.meta.key == "G"
    c1, c2 = up.tracks[0].events
    assert (c1.symbol, c1.root, c1.bass) == ("Gmaj7/B", "G", "B")
    assert c2.symbol == "C6/9"
    assert c1.pitches == tuple(p + 2 for p in song.tracks[0].events[0].pitches)
    assert up.tracks[1].events == (Hit(F(0), "kick"), Note(F(0), F(1), 62))
    down = Transpose().run(song, {"semitones": "-4"})
    assert down.meta.key == "Db"  # flat key -> flat spellings
    assert down.tracks[0].events[0].symbol == "Dbmaj7/F"
    minor = Transpose().run(Song(meta=Meta(key="Am"), tracks=()), {"semitones": "1"})
    assert minor.meta.key == "Bbm"


def test_transpose_errors():
    song = Song(tracks=(Track(id="m", events=(Note(F(0), F(1), 126),)),))
    with pytest.raises(StrudelizerError, match="MIDI range") as info:
        Transpose().run(song, {"semitones": "5"})
    assert info.value.location == "track m, bar 1"
    with pytest.raises(StrudelizerError, match="whole number"):
        Transpose().run(song, {"semitones": "up"})


# ---- remap_drums -----------------------------------------------------------------------------


def test_remap_drums(tmp_path):
    path = tmp_path / "kit.yaml"
    path.write_text("clap: snare\ncowbell: null\n")
    song = Song(tracks=(Track(id="d", role="drums", bars=(0,), events=(
        Hit(F(0), "clap", 80), Hit(F(0), "snare", 100), Hit(F(1), "cowbell"), Hit(F(2), "kick"),
    )),))
    out = RemapDrums().run(song, {"map": str(path)})
    assert out.tracks[0].events == (Hit(F(0), "snare", 100), Hit(F(2), "kick"))
    assert out.tracks[0].bars is None


def test_remap_drums_errors(tmp_path):
    path = tmp_path / "kit.yaml"
    path.write_text("clap: gong\n")
    with pytest.raises(StrudelizerError, match="unknown drum 'gong'") as info:
        RemapDrums().run(Song(tracks=()), {"map": str(path)})
    assert info.value.location.endswith(": clap")
    with pytest.raises(StrudelizerError, match="cannot read"):
        RemapDrums().run(Song(tracks=()), {"map": str(tmp_path / "none.yaml")})


def test_p2_passes_compose_via_cli_spec(tmp_path):
    kit = tmp_path / "kit.yaml"
    kit.write_text("closed_hat: shaker\n")
    pipeline = Pipeline(passes=f"arrange:rock,transpose:-2,remap_drums:{kit},quantize,dedupe_bars",
                        importer_options={"bpm": 90})
    with pytest.warns(StrudelizerWarning):
        song = pipeline.transform(pipeline.load(SHEETS / "night_train.txt"))
    drums = {e.drum for t in song.tracks for e in t.events if isinstance(e, Hit)}
    assert "shaker" in drums and "closed_hat" not in drums

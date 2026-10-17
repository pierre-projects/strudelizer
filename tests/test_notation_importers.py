"""ASCII tab, Guitar Pro and MusicXML importers (FR-12 to FR-14)."""

from fractions import Fraction as F

import pytest
from conftest import FIXTURES, SHEETS, has_module

from strudelizer import Pipeline
from strudelizer.core import StrudelizerError, StrudelizerWarning
from strudelizer.core.tab import parse_tab, parse_tuning, staff_line, tuning_from_labels
from strudelizer.core.theory import name_to_midi as m
from strudelizer.importers.ascii_tab import AsciiTabImporter
from strudelizer.importers.chordsheet import ChordSheetImporter

TABS = FIXTURES / "tabs"
needs_gp = pytest.mark.skipif(not has_module("guitarpro"), reason="guitarpro extra not installed")
needs_m21 = pytest.mark.skipif(not has_module("music21"), reason="music21 extra not installed")


def lines(text):
    return list(enumerate(text.strip("\n").splitlines(), 1))


def pitches(song, track=0):
    return [(e.start, e.duration, e.pitch) for e in song.tracks[track].events]


# ---- core.tab --------------------------------------------------------------------------


def test_tunings_from_labels_and_names():
    assert tuning_from_labels(["e", "B", "G", "D", "A", "E"]) == (40, 45, 50, 55, 59, 64)
    assert tuning_from_labels(["e", "B", "G", "D", "A", "D"])[0] == m("d2")  # drop D, not D3
    assert tuning_from_labels(["G", "D", "A", "E"]) == (28, 33, 38, 43)  # 4-string bass
    assert tuning_from_labels(["e", "B", "G", "D", "A", "E", "B"])[0] == m("b1")  # 7-string
    assert parse_tuning("drop d", 6) == (38, 45, 50, 55, 59, 64)
    assert parse_tuning("D A D G B E", 6) == parse_tuning("DADGBE", 6)
    assert parse_tuning("C2 G2 C3 F3 A3 D4", 6)[0] == 36
    with pytest.raises(ValueError, match="has 4 notes for a 6-string"):
        parse_tuning("E A D G", 6)


def test_staff_lines_ignore_techniques_and_keep_frets():
    assert staff_line("D|--3h5--x--7b9~~-|  x2").repeat == 2
    assert staff_line("Am   G   C") is None
    assert staff_line("|-----|-----|") is not None
    result = parse_tab(lines("""
e|-----|
B|-----|
G|--5h7|
D|-----|
A|-----|
E|0----|
"""))
    assert [n.pitch for n in result.notes] == [40, 60, 62]


def test_rhythm_modes():
    tab = lines("""
e|0---0-0-|
B|--------|
G|--------|
D|--------|
A|--------|
E|--------|
""")
    assert [n.start for n in parse_tab(tab, rhythm="even8").notes] == [F(0), F(1, 2), F(1)]
    assert [n.start for n in parse_tab(tab, rhythm="even16").notes] == [F(0), F(1, 4), F(1, 2)]
    # columns: positions 0, 4, 6 of 8 columns in one 4/4 measure
    columns = parse_tab(tab, rhythm="columns")
    assert [n.start for n in columns.notes] == [F(0), F(2), F(3)]
    assert columns.length == 4


def test_dead_notes_keep_their_slot():
    tab = lines("""
e|--------|
B|--------|
G|--------|
D|0-x-0---|
A|--------|
E|--------|
""")
    assert [n.start for n in parse_tab(tab).notes] == [F(0), F(1)]


def test_blocks_with_wrong_string_counts_are_reported():
    result = parse_tab(lines("""
e|--0--|
B|--1--|
G|--0--|
"""))
    assert not result.notes
    assert [p[0] for p in result.problems] == [1, 2, 3]


# ---- ASCII tab importer ------------------------------------------------------------------


def test_drop_d_riff():
    with pytest.warns(StrudelizerWarning, match="line 15: skipped unparsed line"):
        song = AsciiTabImporter().load(TABS / "riff.txt", {})
    assert (song.meta.title, song.meta.bpm) == ("Rust Belt Riff", 132)
    first = pitches(song)[:3]
    assert first == [(F(0), F(1, 2), m("d2")), (F(0), F(1, 2), m("a2")), (F(0), F(1, 2), m("d3"))]
    # the block repeats (x2): bar 3 starts like bar 1
    assert [p for s, _, p in pitches(song) if s == 8] == [m("d2"), m("a2"), m("d3")]
    # bend 8b10 on the B string keeps both frets
    assert {m("g4"), m("a4")} <= {p for _, _, p in pitches(song)}


def test_capo_and_columns():
    song = AsciiTabImporter().load(TABS / "capo_waltz.tab", {"tab_rhythm": "columns"})
    assert song.meta.time_signature == (3, 4)
    # C shape with capo 2 sounds D: A string fret 3 + 2 = D3
    assert pitches(song)[0] == (F(0), F(1, 2), m("d3"))
    assert [s for s, _, _ in pitches(song)[:6]] == [F(0), F(1, 2), F(1), F(3, 2), F(2), F(5, 2)]
    no_capo = AsciiTabImporter().load(TABS / "capo_waltz.tab", {"tab_rhythm": "columns", "capo": "0"})
    assert pitches(no_capo)[0][2] == m("c3")


def test_bass_tab_and_tuning_option():
    song = AsciiTabImporter().load(TABS / "walking_bass.tab", {"tab_rhythm": "columns"})
    assert (song.tracks[0].id, song.tracks[0].role) == ("bass", "bass")
    assert pitches(song)[:4] == [(F(0), F(1), m("a1")), (F(1), F(1), m("b1")), (F(2), F(1), m("d2")), (F(3), F(1), m("e2"))]
    drop = AsciiTabImporter().load(TABS / "walking_bass.tab", {"tab_rhythm": "columns", "tuning": "D A D G"})
    assert pitches(drop)[0][2] == m("a1")  # A string unchanged
    with pytest.raises(StrudelizerError, match="tuning"):
        AsciiTabImporter().load(TABS / "walking_bass.tab", {"tuning": "E A D G B E"})


def test_tab_detection():
    imp = AsciiTabImporter()
    assert imp.can_handle(TABS / "riff.txt")
    assert not imp.can_handle(SHEETS / "night_train.txt")
    assert not imp.can_handle(SHEETS / "lantern_riff.cho")


def test_chord_sheet_imports_tab_blocks_with_capo():
    song = ChordSheetImporter().load(SHEETS / "lantern_riff.cho", {})
    chords = [e.symbol for e in song.tracks[0].events]
    assert chords[:4] == ["A", "D", "E", "A"]  # G C D G with capo 2
    tab = song.tracks[1]
    assert tab.id == "guitar"
    first = min(tab.events, key=lambda e: (e.start, e.pitch))
    assert first.start == F(16) and first.pitch == m("a2")  # after the 4-bar verse; E fret 3 + capo 2
    assert [(s.name, s.start_bar, s.length) for s in song.sections] == [("verse", 0, 4), ("riff", 4, 2)]


# ---- Guitar Pro --------------------------------------------------------------------------


@needs_gp
def test_guitar_pro_song():
    with pytest.warns(StrudelizerWarning, match="2 dead notes, 1 grace notes"):
        song = Pipeline(passes=None).load(FIXTURES / "gp" / "song.gp5")
    assert (song.meta.title, song.meta.bpm) == ("Harbor Steps", 112)
    by_id = {t.id: t for t in song.tracks}
    assert [(t.id, t.role) for t in song.tracks] == [
        ("rhythm_guitar", "chords"), ("lead", "melody"), ("bass", "bass"), ("drums", "drums"),
    ]
    # drop D: low string open = D2
    assert [e.pitch for e in by_id["rhythm_guitar"].events[:3]] == [m("d2"), m("a2"), m("d3")]
    lead = [(e.start, e.duration, e.pitch) for e in by_id["lead"].events]
    assert lead[0] == (F(4), F(1), m("g4"))  # B string fret 5 + capo 3
    assert (F(6), F(3), m("c5")) in lead  # tied across the bar line: 2 + 1 beats
    assert (F(9), F(1, 3), m("a#4")) in lead  # triplet
    assert (F(12), F(3), m("a#4")) in lead  # grace ornament dropped, main note kept
    assert lead[-1] == (F(24), F(6), m("a#4"))  # 2nd ending tied into the outro
    assert {e.drum for e in by_id["drums"].events} == {"kick", "snare", "closed_hat", "crash"}
    # 1 |: 2 3 |1. 4 :|2. 5 | 6  ->  1 2 3 4 2 3 5 6
    assert [(s.name, s.start_bar, s.length) for s in song.sections] == [
        ("intro", 0, 1), ("verse", 1, 3), ("verse", 4, 3), ("outro", 7, 1),
    ]


@needs_gp
def test_guitar_pro_unfold():
    from types import SimpleNamespace as H

    from strudelizer.importers.guitarpro import unfold

    def h(open_=False, close=-1, alt=0):
        return H(isRepeatOpen=open_, repeatClose=close, repeatAlternative=alt)

    assert unfold([h(), h(True), h(), h(alt=1, close=1), h(alt=2), h()]) == [0, 1, 2, 3, 1, 2, 4, 5]
    assert unfold([h(True), h(close=2)]) == [0, 1, 0, 1, 0, 1]  # play 3 times
    assert unfold([h(), h(close=1)]) == [0, 1, 0, 1]  # no open sign: back to the start


@needs_gp
def test_guitar_pro_bad_file(tmp_path):
    bad = tmp_path / "bad.gp5"
    bad.write_bytes(b"not a guitar pro file")
    with pytest.raises(StrudelizerError) as info:
        Pipeline(passes=None).load(bad)
    assert info.value.stage == "import:guitarpro" and info.value.fix


# ---- MusicXML -------------------------------------------------------------------------------


@needs_m21
def test_musicxml_score():
    song = Pipeline(passes=None).load(FIXTURES / "musicxml" / "score.musicxml")
    assert (song.meta.title, song.meta.bpm, song.meta.key, song.meta.pickup_beats) == ("Lighthouse Hymn", 96, "C", F(1))
    chords, melody, bass = song.tracks
    assert [e.symbol for e in chords.events] == ["C", "Am7", "Dm7", "G7", "C", "Am7", "F/A", "Gsus4", "Fmaj7"]
    slash = chords.events[6]
    assert (slash.root, slash.bass) == ("F", "A")
    notes = [(e.start, e.duration, e.pitch) for e in melody.events]
    assert notes[:2] == [(F(0), F(1, 2), m("g4")), (F(1, 2), F(1, 2), m("a4"))]  # the pickup
    assert (F(3), F(3), m("d5")) in notes  # tied across the bar line
    assert (F(23), F(4), m("a#4")) in notes  # tied from the 2nd ending into the last bar
    assert len(notes) == 17  # 1st and 2nd ending unfolded
    assert (bass.role, bass.instrument) == ("bass", "gm:32")


@needs_m21
def test_compressed_mxl_matches():
    a = Pipeline(passes=None).load(FIXTURES / "musicxml" / "score.musicxml")
    b = Pipeline(passes=None).load(FIXTURES / "musicxml" / "score_compressed.mxl")
    assert a.tracks == b.tracks


@needs_m21
def test_musicxml_bad_file(tmp_path):
    bad = tmp_path / "bad.musicxml"
    bad.write_text("<score-partwise><oops")
    with pytest.raises(StrudelizerError) as info:
        Pipeline(passes=None).load(bad)
    assert info.value.stage == "import:musicxml"


def test_dod_commands(tmp_path):
    """The P3 gate commands produce Strudel code (validity is checked by
    test_strudel_validity on the golden copies of these outputs)."""
    from strudelizer.cli import main

    jobs = [("tabs/riff.txt", None), ("gp/song.gp5", "guitarpro"), ("musicxml/score.musicxml", "music21")]
    for rel, module in jobs:
        if not has_module(module):
            continue
        out = tmp_path / (rel.replace("/", "_") + ".js")
        assert main([str(FIXTURES / rel), "-o", str(out)]) == 0
        golden = (FIXTURES / rel).with_suffix(".js")
        assert out.read_bytes() == golden.read_bytes(), rel

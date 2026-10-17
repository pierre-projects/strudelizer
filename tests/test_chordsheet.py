from fractions import Fraction as F

import pytest
from conftest import SHEETS

from strudelizer.core import StrudelizerError, StrudelizerWarning
from strudelizer.core.theory import chord_name, parse_chord, split_symbol
from strudelizer.importers.chordsheet import ChordSheetImporter

# Decision 2: every spelling the parser must accept, with its canonical form
DECISION_2 = [
    ("C", "C", "maj", (), None),
    ("Cm", "C", "m", (), None),
    ("Cmin", "C", "m", (), None),
    ("C-", "C", "m", (), None),
    ("C7", "C", "7", (), None),
    ("Cmaj7", "C", "maj7", (), None),
    ("CM7", "C", "maj7", (), None),
    ("C^7", "C", "maj7", (), None),
    ("CΔ", "C", "maj7", (), None),
    ("Cm7", "C", "m7", (), None),
    ("C6", "C", "6", (), None),
    ("Cm6", "C", "m6", (), None),
    ("C9", "C", "7", ("9",), None),
    ("Cadd9", "C", "maj", ("add9",), None),
    ("Csus2", "C", "sus2", (), None),
    ("Csus4", "C", "sus4", (), None),
    ("Cdim", "C", "dim", (), None),
    ("C°", "C", "dim", (), None),
    ("Cm7b5", "C", "m7b5", (), None),
    ("Cø", "C", "m7b5", (), None),
    ("Caug", "C", "aug", (), None),
    ("C+", "C", "aug", (), None),
    ("C/E", "C", "maj", (), "E"),
    ("F#m7b5/C", "F#", "m7b5", (), "C"),
    ("Bb6/9", "Bb", "6", ("9",), None),
    ("E♭maj7", "Eb", "maj7", (), None),
]


@pytest.mark.parametrize("token,root,quality,extensions,bass", DECISION_2)
def test_every_decision_2_spelling_parses_to_canonical_form(token, root, quality, extensions, bass):
    chord = parse_chord(token)
    assert chord is not None, token
    assert (chord.root, chord.quality, chord.extensions, chord.bass) == (root, quality, extensions, bass)
    assert chord.pitches()  # every canonical chord has a voicing


@pytest.mark.parametrize("token", ["Hm7", "Hello", "Day", "Bad", "I", "Bridge", "Verse", "C/", "Cxyz", "c", ""])
def test_strict_grammar_rejects_non_chords(token):
    assert parse_chord(token) is None


def test_voicings():
    assert parse_chord("C").pitches() == (48, 52, 55)
    assert parse_chord("C/E").pitches() == (40, 48, 52, 55)  # slash bass below
    assert parse_chord("C/E").pitches(with_bass=False) == (48, 52, 55)
    assert parse_chord("Am7").pitches() == (57, 60, 64, 67)
    assert chord_name("7", ("9",)) == "9"
    assert split_symbol("Bb6/9/D") == ("Bb", "6/9", "D")


def load(name, **options):
    return ChordSheetImporter().load(SHEETS / name, options)


def chords(song):
    return [(e.start, e.duration, e.symbol) for e in song.tracks[0].events]


def test_chordpro_fixture():
    with pytest.warns(StrudelizerWarning) as rec:
        song = load("harbor_lights.cho")
    messages = [str(w.message) for w in rec]
    assert any("line 24" in m and "[Q7]" in m for m in messages)
    assert any("line 32" in m and "unknown directive {flourish}" in m for m in messages)
    assert song.meta.title == "Harbor Lights"
    assert song.meta.key == "G"
    assert song.meta.bpm == 92  # from {tempo}, no default-tempo warning
    assert not any("no tempo" in m for m in messages)
    assert song.meta.pickup_beats == F(2)
    events = chords(song)
    assert events[0] == (F(0), F(2), "D")  # the pickup chord lasts the pickup
    assert events[1] == (F(2), F(4), "G")  # bar 1
    assert [(s.name, s.start_bar, s.length) for s in song.sections] == [
        ("verse", 0, 8), ("chorus", 8, 8), ("verse_2", 16, 15), ("chorus", 31, 8), ("bridge", 39, 4),
    ]
    # {chorus} repeats the first chorus
    # bars 8-15 (chorus) start at beat 8*4 - 2 because of the 2-beat pickup
    def section_symbols(bar):
        return [s for start, _, s in events if bar * 4 - 2 <= start < (bar + 8) * 4 - 2]

    assert section_symbols(8)[:2] == ["Em", "Bm7"]
    assert section_symbols(31) == section_symbols(8)
    slash = next(e for e in song.tracks[0].events if e.symbol == "G/B")
    assert (slash.root, slash.quality, slash.bass) == ("G", "maj", "B")
    assert slash.pitches == (47, 55, 59, 62)


def test_chords_over_lyrics_fixture():
    with pytest.warns(StrudelizerWarning) as rec:
        song = load("paper_kites.txt", bpm=84)
    messages = [str(w.message) for w in rec]
    assert any("line 23" in m and "'Hm7'" in m for m in messages)
    assert song.meta.title == "Paper Kites"  # first text line
    assert song.meta.time_signature == (3, 4)
    assert song.meta.bpm == 84
    events = chords(song)
    assert events[0] == (F(0), F(1), "E")  # one-beat pickup
    assert events[1] == (F(1), F(3), "Am")
    lyrics = {"Paper", "kites", "strings", "every", "Let", "someday"}
    assert not any(s.split("/")[0] in lyrics for _, _, s in events)
    assert [s.name for s in song.sections] == ["intro", "verse", "chorus"]


def test_bar_line_fixture():
    with pytest.warns(StrudelizerWarning) as rec:
        song = load("night_train.txt", bpm=90)
    messages = [str(w.message) for w in rec]
    assert any("line 16" in m and "'Fxx7'" in m for m in messages)
    assert not any("no tempo" in m for m in messages)
    events = chords(song)
    assert events[:3] == [(F(2), F(4), "Cm"), (F(6), F(4), "Cmin"), (F(10), F(4), "C-")]
    by_symbol = {s: (start, d) for start, d, s in events}
    assert by_symbol["Ab^7"][1] == F(3) and by_symbol["G7"][1] == F(1)  # "Ab^7 / / G7"
    assert by_symbol["EbΔ"][1] == F(8)  # the empty bar holds the chord
    assert [s for _, _, s in events].count("Cm/Bb") == 2  # "%" repeats the bar
    assert [s for _, _, s in events].count("Cm7") == 2  # |: ... :| repeats
    assert [s for _, _, s in events].count("Abadd9") == 2  # x2 repeats the line
    assert [(s.name, s.start_bar) for s in song.sections] == [("intro", 0), ("verse", 4), ("chorus", 20), ("outro", 40)]


def test_default_tempo_warns(tmp_path):
    path = tmp_path / "s.txt"
    path.write_text("| C | G |\n")
    with pytest.warns(StrudelizerWarning, match="using 100 bpm"):
        song = ChordSheetImporter().load(path, {})
    assert song.meta.bpm == 100


def test_beats_per_chord_and_inline_chords(tmp_path):
    path = tmp_path / "s.cho"
    path.write_text("{tempo: 80}\n[C]one [G]two [Am]three [F]four\n")
    song = ChordSheetImporter().load(path, {"beats_per_chord": "2"})
    assert chords(song) == [(F(0), F(2), "C"), (F(2), F(2), "G"), (F(4), F(2), "Am"), (F(6), F(2), "F")]


def test_section_mid_bar_holds_to_the_bar_line(tmp_path):
    path = tmp_path / "s.txt"
    path.write_text("{tempo: 80}\nC G Am\n[Chorus]\nF\n")
    song = ChordSheetImporter().load(path, {"beats_per_chord": "2"})
    # Am holds to the bar line where the chorus starts; the song ends on a bar line too
    assert chords(song)[-2:] == [(F(4), F(4), "Am"), (F(8), F(4), "F")]
    assert [(s.name, s.start_bar) for s in song.sections] == [("chorus", 2)]


def test_lyrics_with_chord_like_words_are_not_chords(tmp_path):
    path = tmp_path / "s.txt"
    path.write_text("{tempo: 80}\nC\nAm I blue\nA day in the life\nG\n")
    song = ChordSheetImporter().load(path, {})
    assert [s for _, _, s in chords(song)] == ["C", "G"]


def test_errors(tmp_path):
    with pytest.raises(StrudelizerError, match="file not found"):
        ChordSheetImporter().load(tmp_path / "missing.txt", {})
    empty = tmp_path / "e.txt"
    empty.write_text("just some words\n")
    with pytest.raises(StrudelizerError, match="no chords found") as info:
        ChordSheetImporter().load(empty, {})
    assert info.value.stage == "import:chordsheet"
    big = tmp_path / "p.txt"
    big.write_text("{pickup: 4}\n| C |\n")
    with pytest.raises(StrudelizerError, match="pickup must be between"):
        ChordSheetImporter().load(big, {"bpm": 90})


@pytest.mark.parametrize("directive", ["x_pickup", "pickup"])
def test_pickup_directive_canonical_and_alias(tmp_path, directive):
    path = tmp_path / "p.cho"
    path.write_text(f"{{tempo: 90}}\n{{{directive}: 1}}\n[G]up [C]beat\n", encoding="utf-8")
    song = ChordSheetImporter().load(path, {})
    assert song.meta.pickup_beats == F(1)
    assert chords(song)[0] == (F(0), F(1), "G")
    # the --pickup option wins over the directive
    assert ChordSheetImporter().load(path, {"pickup": "2"}).meta.pickup_beats == F(2)


def test_tab_blocks_are_skipped(tmp_path):
    path = tmp_path / "t.cho"
    path.write_text("{tempo: 90}\n[C]a\n{start_of_tab}\ne|---0---|\n{end_of_tab}\n[G]b\n")
    with pytest.warns(StrudelizerWarning, match="tab block"):
        song = ChordSheetImporter().load(path, {})
    assert [s for _, _, s in chords(song)] == ["C", "G"]

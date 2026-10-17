"""P1 gate: every generated .js evaluates in the pinned Strudel runtime and
plays the notes the IR says, bar by bar.

Needs Node and `npm ci --prefix tests/strudel` (see the Makefile).
"""

import json
import shutil
import subprocess
import warnings
from collections import Counter
from fractions import Fraction as F

import pytest
from conftest import (
    FIXTURES,
    IR_FIXTURES,
    MIDI_FIXTURES,
    SHEET_FIXTURES,
    SHEETS,
    STYLES,
    TESTS,
    sheet_js_name,
    sheet_passes,
)

from strudelizer import Pipeline, registry
from strudelizer.core import Chord, Hit, Note
from strudelizer.core.time import beats_per_bar, song_bars, song_length_bars, time_signature
from strudelizer.emitters.strudel import _chord_symbol

STRUDEL_DIR = TESTS / "strudel"
CYCLES = 64  # the longest fixture is ~50 bars; every bar of every song is checked

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (STRUDEL_DIR / "node_modules" / "@strudel" / "core").exists(),
    reason="needs node and `npm ci --prefix tests/strudel`",
)


def _cases():
    for name in MIDI_FIXTURES:
        yield name, FIXTURES / f"{name}.js", lambda n=name: Pipeline().transform(Pipeline(passes=None).load(FIXTURES / f"{n}.mid"))
    for name in IR_FIXTURES:
        yield name, FIXTURES / "ir" / f"{name}.js", lambda n=name: Pipeline.read_ir(FIXTURES / "ir" / f"{n}.ir.json")
    for sheet, options in SHEET_FIXTURES.items():
        for style in [None, *STYLES]:
            def make(sheet=sheet, options=options, style=style):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    pipeline = Pipeline(passes=sheet_passes(style), importer_options=options)
                    return pipeline.transform(pipeline.load(SHEETS / sheet))

            yield sheet_js_name(sheet, style), SHEETS / sheet_js_name(sheet, style), make


CASES = list(_cases())


@pytest.fixture(scope="module")
def strudel_results():
    files = [str(js) for _, js, _ in CASES]
    proc = subprocess.run(
        ["node", "validate.mjs", "--cycles", str(CYCLES), *files],
        cwd=STRUDEL_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        results = json.loads(proc.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"validate.mjs crashed:\n{proc.stderr}")
    return {r["file"]: r for r in results}


def _expected(song, profile="default"):
    drums = registry.get_profile(profile)["drums"]
    drum_map = drums["map"]
    bar_len = beats_per_bar(song.meta)
    n_bars = song_length_bars(song)
    hits, notes, chord_onsets = Counter(), Counter(), set()
    for track in song.tracks:
        # song_bars applies the pickup offset: bar 1 must start on cycle 1
        for bar_index, bar in enumerate(song_bars(song, track.events)):
            for e in bar:
                cycle = bar_index + e.start / bar_len
                if isinstance(e, Hit):
                    bank = None if e.drum in drums["unbanked"] else drums["bank"]
                    hits[(cycle, drum_map[e.drum], bank)] += 1
                elif isinstance(e, Note):
                    notes[(cycle, e.pitch)] += 1
                elif isinstance(e, Chord):
                    if _chord_symbol(e) is not None:
                        chord_onsets.add(cycle)
                    else:
                        for p in e.pitches:
                            notes[(cycle, p)] += 1
    return n_bars, hits, notes, chord_onsets


@pytest.mark.parametrize("name,js,make_song", CASES, ids=[c[0] for c in CASES])
def test_plays_in_strudel(strudel_results, name, js, make_song):
    result = strudel_results[str(js)]
    assert result["ok"], result["error"]
    song = make_song()
    num = time_signature(song.meta)[0]
    assert result["cps"] == pytest.approx(song.meta.bpm / 60 / num)

    n_bars, want_hits, want_notes, chord_onsets = _expected(song)
    assert n_bars <= CYCLES
    got_hits, got_notes = Counter(), Counter()
    for ev in result["events"]:
        start = F(ev["start"])
        if start >= n_bars:
            continue
        if "note" in ev:
            got_notes[(start, ev["note"])] += 1
        else:
            got_hits[(start, ev["s"], ev.get("bank"))] += 1

    assert got_hits == want_hits
    missing = want_notes - got_notes
    assert not missing, f"notes missing in Strudel output: {sorted(missing.items())[:5]}"
    extra = got_notes - want_notes
    # only voiced chords may add notes (their pitches come from Strudel's dictionary)
    assert all(start in chord_onsets for start, _ in extra), sorted(extra.items())[:5]
    for onset in chord_onsets:
        assert sum(n for (s, _), n in extra.items() if s == onset) >= 3

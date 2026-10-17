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
    NOTATION_FIXTURES,
    TESTS,
    golden_base,
    has_module,
    sheet_js_name,
    sheet_passes,
)

from strudelizer import Pipeline, registry
from strudelizer.core import Chord, Hit, Note
from strudelizer.core.time import beats_per_bar, slice_spans, song_bars, song_length_bars, time_signature
from strudelizer.emitters.strudel import _chord_symbol, _Writer

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
    for rel, options, module in NOTATION_FIXTURES:
        if not has_module(module):
            continue  # the extra is not installed; scripts/check.py insists on it

        def make(rel=rel, options=options):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pipeline = Pipeline(importer_options=options)
                return pipeline.transform(pipeline.load(FIXTURES / rel))

        yield rel, golden_base(rel).with_suffix(".js"), make


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
    """What Strudel must play, from the IR. Notes start at their IR start and
    again only where the emitter splits a held note: at the end of a tie
    span (MAX_TIE_BARS, or a section start). Hits and chords are per bar."""
    drums = registry.get_profile(profile)["drums"]
    drum_map = drums["map"]
    bar_len = beats_per_bar(song.meta)
    n_bars = song_length_bars(song)
    writer = _Writer(song, registry.get_profile(profile))
    hits, notes, chord_onsets = Counter(), Counter(), set()

    def segments(events, spans):
        starts = [b * bar_len - writer.offset for b, _ in spans]
        ends = [(b + k) * bar_len - writer.offset for b, k in spans]
        for (first, _), seg in zip(spans, slice_spans(events, starts, ends)):
            for e in seg:
                yield first + e.start / bar_len, e

    for t_index, track in enumerate(writer.tracks):
        kinds = {k.func: k for k in writer.kinds[t_index] if k.func != "s"}
        pitched = [e for e in track.events if isinstance(e, Note)]
        voiced = []
        for e in track.events:
            if isinstance(e, Chord):
                if _chord_symbol(e) is not None:
                    voiced.append(e)
                else:
                    pitched += [Note(e.start, e.duration, p) for p in e.pitches]
        hit_events = [e for e in track.events if isinstance(e, Hit)]
        # song_bars applies the pickup offset: bar 1 must start on cycle 1
        for bar_index, bar in enumerate(song_bars(song, hit_events)):
            for e in bar:
                bank = None if e.drum in drums["unbanked"] else drums["bank"]
                hits[(bar_index + e.start / bar_len, drum_map[e.drum], bank)] += 1
        if pitched:
            for cycle, e in segments(pitched, kinds["note"].spans):
                notes[(cycle, e.pitch)] += 1
        if voiced:
            for cycle, _ in segments(voiced, kinds["chord"].spans):
                chord_onsets.add(cycle)
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

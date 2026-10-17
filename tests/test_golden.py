"""Golden-file tests: any change in importer or emitter output fails here."""

import pytest
from conftest import (
    FIXTURES,
    IR_FIXTURES,
    MIDI_FIXTURES,
    SHEET_FIXTURES,
    SHEETS,
    STYLES,
    check_golden,
    sheet_js_name,
    sheet_passes,
)

from strudelizer import Pipeline


def test_fixture_generator_reproduces_checked_in_midi():
    import make_fixtures

    for name, data in make_fixtures.build_all().items():
        assert (FIXTURES / f"{name}.mid").read_bytes() == data, f"{name}.mid is stale; rerun make_fixtures.py"


@pytest.mark.parametrize("name", MIDI_FIXTURES)
def test_import_ir_golden(name):
    song = Pipeline(passes=None).load(FIXTURES / f"{name}.mid")
    check_golden(FIXTURES / f"{name}.ir.json", song.to_json())


@pytest.mark.parametrize("name", MIDI_FIXTURES)
def test_one_shot_js_golden(name):
    code = Pipeline().run(FIXTURES / f"{name}.mid")
    check_golden(FIXTURES / f"{name}.js", code)


@pytest.mark.parametrize("name", IR_FIXTURES)
def test_ir_fixture_js_golden(name):
    song = Pipeline.read_ir(FIXTURES / "ir" / f"{name}.ir.json")
    code = Pipeline(passes=None).emit(song)
    check_golden(FIXTURES / "ir" / f"{name}.js", code)


@pytest.mark.filterwarnings("ignore::strudelizer.StrudelizerWarning")
@pytest.mark.parametrize("sheet", list(SHEET_FIXTURES))
def test_chord_sheet_ir_golden(sheet):
    song = Pipeline(passes=None, importer_options=SHEET_FIXTURES[sheet]).load(SHEETS / sheet)
    check_golden(SHEETS / f"{sheet.rsplit('.', 1)[0]}.ir.json", song.to_json())


@pytest.mark.filterwarnings("ignore::strudelizer.StrudelizerWarning")
@pytest.mark.parametrize("style", [None, *STYLES])
@pytest.mark.parametrize("sheet", list(SHEET_FIXTURES))
def test_chord_sheet_js_golden(sheet, style):
    pipeline = Pipeline(passes=sheet_passes(style), importer_options=SHEET_FIXTURES[sheet])
    check_golden(SHEETS / sheet_js_name(sheet, style), pipeline.run(SHEETS / sheet))


def _pattern_text(code: str) -> int:
    """Characters inside mini-notation strings: the part dedupe can shrink
    (the header and sound chains are the same either way)."""
    import re

    return sum(len(m) for m in re.findall(r'"[^"]*"|`[^`]*`', code))


def test_dedupe_makes_patterns_at_least_half_as_long():
    path = FIXTURES / "multitrack_repeats.mid"
    with_dedupe = Pipeline(passes="quantize:16+8t,dedupe_bars").run(path)
    without = Pipeline(passes="quantize:16+8t").run(path)
    assert _pattern_text(with_dedupe) <= 0.5 * _pattern_text(without)
    assert len(with_dedupe) < len(without)

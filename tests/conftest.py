import os
import sys
from pathlib import Path

import pytest

# Tests always run in strict mode: the IR is validated after every pass.
# Set in the environment so subprocesses (CLI tests) inherit it too.
os.environ["STRUDELIZER_STRICT"] = "1"

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
sys.path.insert(0, str(FIXTURES))  # make_fixtures

MIDI_FIXTURES = ["drums_44", "bassline", "melody_triplets", "multitrack_repeats", "groove_78", "pickup_percussion"]
IR_FIXTURES = ["sections_chords"]
SHEETS = FIXTURES / "sheets"
# chord sheet fixture -> importer options (harbor_lights has its own {tempo})
SHEET_FIXTURES = {
    "harbor_lights.cho": {},
    "paper_kites.txt": {"bpm": 84},
    "night_train.txt": {"bpm": 90},
}
SHEET_FIXTURES["lantern_riff.cho"] = {}  # ChordPro with tab blocks and a capo
STYLES = ["lofi", "rock", "four_on_floor"]

# P3 notation fixtures: (path under fixtures/, importer options, module the
# importer needs). Golden files sit next to each fixture: <stem>.ir.json, <stem>.js.
NOTATION_FIXTURES = [
    ("tabs/riff.txt", {}, None),
    ("tabs/capo_waltz.tab", {"tab_rhythm": "columns"}, None),
    ("tabs/walking_bass.tab", {"tab_rhythm": "columns"}, None),
    ("gp/song.gp5", {}, "guitarpro"),
    ("musicxml/score.musicxml", {}, "music21"),
    ("musicxml/score_compressed.mxl", {}, "music21"),
]


def has_module(name) -> bool:
    import importlib.util

    return name is None or importlib.util.find_spec(name) is not None


def notation_params():
    """pytest params for NOTATION_FIXTURES; extras that are not installed skip."""
    out = []
    for rel, options, module in NOTATION_FIXTURES:
        marks = [] if has_module(module) else [
            pytest.mark.skip(reason=f"{module} not installed (pip install -e \".[all]\")")
        ]
        out.append(pytest.param(rel, options, id=rel, marks=marks))
    return out


def golden_base(rel: str) -> Path:
    path = FIXTURES / rel
    return path.with_name(path.stem)


def sheet_passes(style):
    from strudelizer.pipeline import DEFAULT_PASSES

    return f"arrange:style={style},{DEFAULT_PASSES}" if style else DEFAULT_PASSES


def sheet_js_name(sheet: str, style) -> str:
    stem = sheet.rsplit(".", 1)[0]
    return f"{stem}.{style}.js" if style else f"{stem}.js"
UPDATE_GOLDEN = os.environ.get("STRUDELIZER_UPDATE_GOLDEN") == "1"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def check_golden(path: Path, actual: str) -> None:
    """Compare against a checked-in golden file; rewrite it when updating."""
    import difflib

    if UPDATE_GOLDEN or not path.exists():
        if not UPDATE_GOLDEN:
            pytest.fail(f"missing golden file {path.name}; run with STRUDELIZER_UPDATE_GOLDEN=1")
        path.write_bytes(actual.encode("utf-8"))
        return
    expected = path.read_bytes().decode("utf-8")
    if expected != actual:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"{path.name} (golden)",
                tofile=f"{path.name} (actual)",
            )
        )
        pytest.fail(f"output differs from golden file {path.name}:\n{diff}\n"
                    "If the change is intended, rerun with STRUDELIZER_UPDATE_GOLDEN=1.")

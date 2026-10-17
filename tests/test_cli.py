import json
import shutil
import subprocess
import sys

import mido
import pytest
from conftest import FIXTURES

from strudelizer import Pipeline
from strudelizer.cli import main


def test_one_shot_writes_js(tmp_path, capsys):
    out = tmp_path / "song.js"
    assert main([str(FIXTURES / "groove_78.mid"), "-o", str(out)]) == 0
    assert out.read_bytes() == (FIXTURES / "groove_78.js").read_bytes()
    assert b"\r\n" not in out.read_bytes()


def test_one_shot_options(tmp_path):
    out = tmp_path / "song.js"
    assert main([str(FIXTURES / "bassline.mid"), "-o", str(out), "--profile", "techno", "--passes", "quantize:8"]) == 0
    code = out.read_text()
    assert "(profile: techno)" in code and ".lpf(400).shape(0.4)" in code


def test_one_shot_to_ir_json_by_extension(tmp_path):
    out = tmp_path / "song.ir.json"
    assert main([str(FIXTURES / "drums_44.mid"), "-o", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["tracks"][0]["bars"] == [0, 1, 2, 1]  # passes ran


def test_staged_import_pass_emit_equals_one_shot(tmp_path):
    ir = tmp_path / "a.ir.json"
    ir2 = tmp_path / "b.ir.json"
    js = tmp_path / "a.js"
    src = str(FIXTURES / "multitrack_repeats.mid")
    assert main(["import", src, "-o", str(ir)]) == 0
    assert ir.read_bytes() == (FIXTURES / "multitrack_repeats.ir.json").read_bytes()
    assert main(["pass", str(ir), "--passes", "quantize:16+8t,dedupe_bars", "-o", str(ir2)]) == 0
    assert main(["emit", str(ir2), "-o", str(js)]) == 0
    assert js.read_bytes() == (FIXTURES / "multitrack_repeats.js").read_bytes()


def test_emit_to_stdout(capsysbinary):
    assert main(["emit", str(FIXTURES / "ir" / "sections_chords.ir.json")]) == 0
    assert capsysbinary.readouterr().out == (FIXTURES / "ir" / "sections_chords.js").read_bytes()


def test_list(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    for word in ["importers:", "midi", "passes:", "quantize", "dedupe_bars", "emitters:", "strudel", "ir_json", "profiles:", "lofi", "techno"]:
        assert word in out


def test_error_names_stage_location_and_fix(tmp_path, capsys):
    assert main([str(FIXTURES / "bassline.mid"), "--passes", "quantize:7"]) == 1
    err = capsys.readouterr().err
    assert "error [pass:quantize] at option grid='7'" in err
    assert "fix:" in err


def test_invalid_ir_is_rejected(tmp_path, capsys):
    bad = tmp_path / "bad.ir.json"
    bad.write_text('{"tracks": [{"events": [{"type": "note", "start": "x", "duration": "1", "pitch": 60}]}]}')
    assert main(["emit", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "error [import:ir] at tracks[0].events[0].start" in err

    bad.write_text("{not json")
    assert main(["emit", str(bad)]) == 1
    assert "line 1, column 2" in capsys.readouterr().err


def test_warnings_go_to_stderr(tmp_path, capsys):
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    track.extend([
        mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100)),
        mido.Message("note_on", note=60, velocity=90),
        mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(140), time=1920),
        mido.Message("note_off", note=60, time=1920 * 3),
    ])
    mid.tracks.append(track)
    path = tmp_path / "tempo.mid"
    mid.save(str(path))
    assert main([str(path), "-o", str(tmp_path / "t.js")]) == 0
    err = capsys.readouterr().err
    assert err.startswith("warning [import:midi]: tempo changes found")


def test_p2_gate_command(tmp_path):
    """`strudelize chords.txt --bpm 90 --style lofi -o out.js`: a chord sheet
    becomes chords + bass + drums. The output equals the golden file that the
    Strudel validity test evaluates."""
    from conftest import SHEETS

    out = tmp_path / "out.js"
    exe = _console_script() or "strudelize"
    result = subprocess.run(
        [exe, str(SHEETS / "night_train.txt"), "--bpm", "90", "--style", "lofi", "-o", str(out)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == (SHEETS / "night_train.lofi.js").read_bytes()
    code = out.read_text(encoding="utf-8")
    for part in ("// chords (chords)", "// drums (drums)", "// bass (bass)", ".voicing()", "setcps(90/60/4)"):
        assert part in code
    assert "line 16: skipped unparsed line" in result.stderr


def test_style_and_arrange_pass_conflict(capsys):
    from conftest import SHEETS

    assert main([str(SHEETS / "night_train.txt"), "--style", "lofi", "--passes", "arrange:rock"]) == 1
    assert "--style and an arrange pass" in capsys.readouterr().err


def test_import_options_reach_the_importer(tmp_path):
    from conftest import SHEETS

    out = tmp_path / "a.ir.json"
    assert main(["import", str(SHEETS / "night_train.txt"), "--bpm", "75", "--pickup", "1", "-o", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["meta"]["bpm"] == 75 and data["meta"]["pickup_beats"] == "1"


def test_python_api_matches_cli():
    assert Pipeline("midi", "quantize:16+8t,dedupe_bars", "strudel").run(FIXTURES / "bassline.mid") == (
        FIXTURES / "bassline.js"
    ).read_text()


def _console_script():
    import sysconfig

    return shutil.which("strudelize", path=sysconfig.get_path("scripts")) or shutil.which("strudelize")


@pytest.mark.skipif(_console_script() is None, reason="console script not installed (pip install -e .)")
def test_console_script_is_installed():
    result = subprocess.run([_console_script(), "list"], capture_output=True, text=True)
    assert result.returncode == 0 and "midi" in result.stdout


def test_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "strudelizer.cli", "list"], capture_output=True, text=True)
    assert result.returncode == 0 and "strudel" in result.stdout

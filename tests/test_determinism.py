"""NFR-5: same input + options -> byte-identical output, across processes."""

import os
import subprocess
import sys

import pytest
from conftest import FIXTURES, MIDI_FIXTURES

from strudelizer import Pipeline


@pytest.mark.parametrize("name", MIDI_FIXTURES)
def test_repeat_runs_identical(name):
    path = FIXTURES / f"{name}.mid"
    assert Pipeline().run(path) == Pipeline().run(path)
    assert Pipeline(passes=None).load(path).to_json() == Pipeline(passes=None).load(path).to_json()


@pytest.mark.parametrize("seed", ["0", "12345"])
def test_identical_across_hash_seeds(seed):
    env = dict(os.environ, PYTHONHASHSEED=seed)
    for name in ("multitrack_repeats", "drums_44"):
        out = subprocess.run(
            [sys.executable, "-m", "strudelizer.cli", str(FIXTURES / f"{name}.mid")],
            capture_output=True,
            env=env,
            check=True,
        ).stdout
        assert out == (FIXTURES / f"{name}.js").read_bytes()
    sheets = FIXTURES / "sheets"
    out = subprocess.run(
        [sys.executable, "-m", "strudelizer.cli", str(sheets / "night_train.txt"), "--bpm", "90", "--style", "lofi"],
        capture_output=True,
        env=env,
        check=True,
    ).stdout
    assert out == (sheets / "night_train.lofi.js").read_bytes()
    midi = [
        subprocess.run(
            [sys.executable, "-m", "strudelizer.cli", str(FIXTURES / "multitrack_repeats.mid"), "--emitter", "midi"],
            capture_output=True, env=env, check=True,
        ).stdout
        for _ in range(2)
    ]
    assert midi[0] == midi[1] and midi[0].startswith(b"MThd")

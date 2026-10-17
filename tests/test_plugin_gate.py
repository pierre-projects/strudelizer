"""P4 gate: a third-party plugin installs and runs with no core changes.

Builds a real wheel for a plugin package (the README's example, read from
README.md so the docs cannot drift), installs it with pip into a fresh
virtual environment, and runs it through the installed `strudelizer`.
Offline: the wheel is made here, and pip runs with --no-index.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import TESTS

from strudelizer import registry

ROOT = TESTS.parent
STRUDEL_DIR = TESTS / "strudel"

PRO_IMPORTER = '''
from strudelizer.registry import Importer


class ProImporter(Importer):
    """Needs an optional extra that is not installed."""

    name = "frets_pro"
    extensions = (".profrets",)
    requires = ("strudelizer_test_module_that_does_not_exist",)
'''


def _readme_plugin() -> tuple[str, str]:
    """The importer source and its entry-point line, from README.md."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    code = re.search(r"```python\n# my_frets/importer\.py\n(.*?)```", readme, re.S).group(1)
    entry = re.search(r'^frets = "(my_frets\.importer:FretsImporter)"$', readme, re.M).group(1)
    return code, entry


def _record_line(name: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(data)}"


def build_wheel(out: Path) -> Path:
    code, entry = _readme_plugin()
    dist = "my_frets-1.0.0.dist-info"
    files = {
        "my_frets/__init__.py": b"",
        "my_frets/importer.py": code.encode(),
        "my_frets/pro.py": PRO_IMPORTER.encode(),
        f"{dist}/METADATA": b"Metadata-Version: 2.1\nName: my-frets\nVersion: 1.0.0\n"
                            b"Requires-Dist: strudelizer\nProvides-Extra: pro\n",
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: strudelizer-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{dist}/entry_points.txt": (
            "[strudelizer.importers]\n"
            f"frets = {entry}\n"
            "frets_pro = my_frets.pro:ProImporter [pro]\n"
        ).encode(),
    }
    record = "\n".join([_record_line(n, d) for n, d in files.items()] + [f"{dist}/RECORD,,"]) + "\n"
    files[f"{dist}/RECORD"] = record.encode()
    wheel = out / "my_frets-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return wheel


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


@pytest.fixture(scope="module")
def plugin_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plugin_gate")
    wheel = build_wheel(tmp)
    venv = tmp / "venv"
    # system site-packages: the venv sees the installed strudelizer and its
    # dependencies, but the plugin goes into the venv only
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True)
    python = venv_python(venv)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", "--disable-pip-version-check", str(wheel)],
        capture_output=True, text=True,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    return python, tmp


def run(python: Path, *args, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(python), "-m", "strudelizer.cli", *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd)


def test_plugin_is_listed_after_pip_install(plugin_env):
    python, tmp = plugin_env
    result = run(python, "list", cwd=tmp)
    assert result.returncode == 0, result.stderr
    assert re.search(r"^  frets\s+Fret lists \(\.frets\): low-E fret numbers, one 8th note each\.\s+\[my-frets\]$",
                     result.stdout, re.M), result.stdout
    assert 'frets_pro' in result.stdout and '(not installed; pip install "my-frets[pro]")' in result.stdout


def test_plugin_converts_a_file(plugin_env):
    python, tmp = plugin_env
    song = tmp / "riff.frets"
    song.write_text("0 3 5 0 3 6 5 7", encoding="utf-8")
    out = tmp / "riff.js"
    result = run(python, str(song), "-o", str(out), "--bpm", "96", cwd=tmp)
    assert result.returncode == 0, result.stderr
    code = out.read_text(encoding="utf-8")
    assert "setcps(96/60/4)" in code
    assert 'note("e2 g2 a2 e2 g2 a#2 a2 b2")' in code
    if shutil.which("node") and (STRUDEL_DIR / "node_modules" / "@strudel" / "core").exists():
        check = subprocess.run(["node", "validate.mjs", "--cycles", "1", str(out)], cwd=STRUDEL_DIR,
                               capture_output=True, text=True, encoding="utf-8")
        result = json.loads(check.stdout)[0]
        assert result["ok"], result["error"]
        assert [e["note"] for e in result["events"]] == [40, 43, 45, 40, 43, 46, 45, 47]


def test_plugin_needing_a_missing_extra_says_how_to_install(plugin_env):
    python, tmp = plugin_env
    song = tmp / "x.profrets"
    song.write_text("0", encoding="utf-8")
    result = run(python, str(song), cwd=tmp)
    assert result.returncode == 1
    assert 'fix: pip install "my-frets[pro]"' in result.stderr


def test_install_was_isolated_and_needed_no_core_change():
    # this interpreter never saw the plugin: it lives only in the venv
    assert "frets" not in [p.name for p in registry.available("importer")]
    assert not (ROOT / "strudelizer" / "importers" / "frets.py").exists()

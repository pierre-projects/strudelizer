"""Task runner: lint, tests and the Strudel check, without needing make.

    python scripts/check.py            # everything (requires all extras)
    python scripts/check.py lint
    python scripts/check.py test [pytest args...]
    python scripts/check.py strudel    # evaluate every golden .js in Strudel
    python scripts/check.py package    # build sdist + wheel and check what is inside
    python scripts/check.py --allow-missing-extras

The full run insists on the optional extras (PyGuitarPro, music21) so their
tests run instead of skipping; install them with `pip install -e ".[all]"`.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRUDEL_DIR = ROOT / "tests" / "strudel"
EXTRAS = {"guitarpro": "guitarpro", "musicxml": "music21"}


def run(cmd: list[str], **kwargs) -> int:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=kwargs.pop("cwd", ROOT), **kwargs)


LINT_PATHS = ["strudelizer", "strudelizer_ui", "tests", "scripts"]
OLDEST_PYTHON = (3, 10)  # requires-python in pyproject.toml


def lint() -> int:
    paths = [p for p in LINT_PATHS if (ROOT / p).exists()]
    code = run([sys.executable, "-m", "pyflakes", *paths])
    return code or grammar()


def grammar() -> int:
    """Parse every file with the oldest supported Python's grammar, so syntax
    newer than 3.10 is caught here and not first in CI."""
    import ast

    bad = []
    for top in LINT_PATHS:
        for path in sorted((ROOT / top).rglob("*.py")) if (ROOT / top).exists() else []:
            if "node_modules" in path.parts:
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8"), str(path), feature_version=OLDEST_PYTHON)
            except SyntaxError as exc:
                bad.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
    for line in bad:
        print(f"not Python {OLDEST_PYTHON[0]}.{OLDEST_PYTHON[1]} syntax: {line}", file=sys.stderr)
    print(f"grammar: {'ok' if not bad else f'{len(bad)} problem(s)'} for Python {OLDEST_PYTHON[0]}.{OLDEST_PYTHON[1]}")
    return 1 if bad else 0


def package() -> int:
    """Build the sdist and wheel and check the wheel holds what a user needs."""
    import tempfile
    import zipfile

    sys.path.insert(0, str(ROOT))
    from strudelizer import __version__

    with tempfile.TemporaryDirectory() as out:
        code = run([sys.executable, "-m", "build", "--outdir", out, str(ROOT)])
        if code:
            return code
        wheels = list(Path(out).glob("*.whl"))
        sdists = list(Path(out).glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            print(f"package: expected one wheel and one sdist, got {wheels + sdists}", file=sys.stderr)
            return 1
        with zipfile.ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())
            dist = f"strudelizer-{__version__}.dist-info"
            metadata = wheel.read(f"{dist}/METADATA").decode("utf-8") if f"{dist}/METADATA" in names else ""
        required = [
            f"{dist}/licenses/LICENSE",
            f"{dist}/entry_points.txt",
            "strudelizer/core/schema.json",
            "strudelizer/profiles/default.yaml",
            "strudelizer/styles/lofi.yaml",
        ]
        if (ROOT / "strudelizer_ui" / "static" / "index.html").exists():
            required.append("strudelizer_ui/static/index.html")
        problems = [f"missing {name}" for name in required if name not in names]
        problems += [f"tests are in the wheel: {n}" for n in sorted(names) if n.startswith("tests/")][:1]
        for field in (f"Version: {__version__}", "License-Expression: MIT", "Requires-Python: >=3.10"):
            if field not in metadata:
                problems.append(f"METADATA lacks {field!r}")
        for line in problems:
            print(f"package: {line}", file=sys.stderr)
        print(f"package: {wheels[0].name} ({len(names)} files), {sdists[0].name}: "
              f"{'ok' if not problems else 'FAILED'}")
        return 1 if problems else 0


def test(args: list[str]) -> int:
    env = dict(os.environ, STRUDELIZER_STRICT="1")
    return run([sys.executable, "-m", "pytest", *args], env=env)


def strudel() -> int:
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        print("strudel: node and npm are required (https://nodejs.org)", file=sys.stderr)
        return 1
    if not (STRUDEL_DIR / "node_modules" / "@strudel" / "core").exists():
        code = run([npm, "ci", "--no-audit", "--no-fund"], cwd=STRUDEL_DIR)
        if code:
            return code
    files = sorted(str(p) for p in (ROOT / "tests" / "fixtures").rglob("*.js"))
    print(f"$ node validate.mjs --cycles 64 <{len(files)} golden files>", flush=True)
    proc = subprocess.run(
        [node, "validate.mjs", "--cycles", "64", *files],
        cwd=STRUDEL_DIR, capture_output=True, text=True, encoding="utf-8",
    )
    import json

    try:
        results = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stderr, file=sys.stderr)
        return 1
    failed = [r for r in results if not r["ok"]]
    for r in failed:
        print(f"FAIL {Path(r['file']).relative_to(ROOT)}: {r['error'].splitlines()[0]}", file=sys.stderr)
    print(f"strudel: {len(results) - len(failed)}/{len(results)} files evaluate")
    return 1 if failed else 0


def extras_ok(allow_missing: bool) -> bool:
    missing = [extra for extra, module in EXTRAS.items() if importlib.util.find_spec(module) is None]
    if not missing:
        return True
    names = ",".join(missing)
    if allow_missing:
        print(f"note: extras not installed ({names}); their tests will be skipped")
        return True
    print(f"extras not installed: {names}. Install with: pip install -e \".[all]\" "
          "(or pass --allow-missing-extras)", file=sys.stderr)
    return False


def main(argv: list[str]) -> int:
    allow_missing = "--allow-missing-extras" in argv
    argv = [a for a in argv if a != "--allow-missing-extras"]
    task = argv[0] if argv else "all"
    if task == "lint":
        return lint()
    if task == "test":
        return test(argv[1:])
    if task == "strudel":
        return strudel()
    if task == "package":
        return package()
    if task != "all":
        print(__doc__, file=sys.stderr)
        return 2
    if not extras_ok(allow_missing):
        return 1
    for name, step in (("lint", lint), ("test", lambda: test(["-q"])), ("strudel", strudel), ("package", package)):
        code = step()
        if code:
            print(f"check: {name} failed", file=sys.stderr)
            return code
    print("check: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

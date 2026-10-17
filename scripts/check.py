"""Task runner: lint, tests and the Strudel check, without needing make.

    python scripts/check.py            # everything (requires all extras)
    python scripts/check.py lint
    python scripts/check.py test [pytest args...]
    python scripts/check.py strudel    # evaluate every golden .js in Strudel
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


def lint() -> int:
    return run([sys.executable, "-m", "pyflakes", "strudelizer", "tests", "scripts"])


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
    if task != "all":
        print(__doc__, file=sys.stderr)
        return 2
    if not extras_ok(allow_missing):
        return 1
    for name, step in (("lint", lint), ("test", lambda: test(["-q"])), ("strudel", strudel)):
        code = step()
        if code:
            print(f"check: {name} failed", file=sys.stderr)
            return code
    print("check: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

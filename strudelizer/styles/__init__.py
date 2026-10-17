"""Arrange style templates (FR-23): data files, not code.

A style says, per time signature, which drum hits to play on which steps of
a bar, the rhythm of the bass, and optionally a rhythm to re-strike the
chords on. `bass.rule` picks the bass notes:

    root        the chord's bass note (the slash note, else the root) on every hit
    root_fifth  alternate bass note and the chord's fifth
    root_octave alternate bass note and the bass note an octave up

Patterns have one character per step: `x` hit, `X` accent, `g` ghost,
`.` rest (spaces are ignored).

Built-in styles are registered in the `strudelizer.styles` entry-point group
like any third-party style, each pointing at a zero-argument loader.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..core.errors import StrudelizerError
from ..core.ir import DRUMS

STAGE = "style"
RULES = ("root", "root_fifth", "root_octave")
STEP_CHARS = set("xXg.")
DEFAULT_VELOCITY = {"accent": 115, "normal": 95, "ghost": 55}

_PATTERN = {"type": "string", "pattern": "^[xXg. ]+$"}

STYLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["meters"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "velocity": {
            "type": "object",
            "properties": {k: {"type": "integer", "minimum": 1, "maximum": 127} for k in DEFAULT_VELOCITY},
            "additionalProperties": False,
        },
        "bass": {
            "type": "object",
            "properties": {
                "rule": {"enum": list(RULES)},
                "octave": {"type": "integer", "minimum": 0, "maximum": 6},
            },
            "additionalProperties": False,
        },
        "meters": {
            "type": "object",
            "minProperties": 1,
            "propertyNames": {"pattern": "^[1-9][0-9]*/(1|2|4|8|16|32)$"},
            "additionalProperties": {
                "type": "object",
                "required": ["steps"],
                "properties": {
                    "steps": {"type": "integer", "minimum": 1, "maximum": 96},
                    "drums": {
                        "type": "object",
                        "propertyNames": {"enum": list(DRUMS)},
                        "additionalProperties": _PATTERN,
                    },
                    "bass": _PATTERN,
                    "chords": {"anyOf": [_PATTERN, {"type": "null"}]},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def _steps(pattern: str) -> str:
    return pattern.replace(" ", "")


def validate_style(data: Any, location: str = "style") -> dict[str, Any]:
    """Check a style mapping, fill in defaults, return a normalised copy."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import best_match

    error = best_match(Draft202012Validator(STYLE_SCHEMA).iter_errors(data))
    if error is not None:
        path = ".".join(str(p) for p in error.absolute_path) or "(top level)"
        raise StrudelizerError(
            STAGE,
            f"invalid style: {error.message}",
            location=f"{location}: {path}",
            fix="see strudelizer/styles/lofi.yaml for the style format",
        )
    meters = {}
    for meter, spec in data["meters"].items():
        steps = spec["steps"]
        patterns = {f"drums.{d}": p for d, p in spec.get("drums", {}).items()}
        if spec.get("bass"):
            patterns["bass"] = spec["bass"]
        if spec.get("chords"):
            patterns["chords"] = spec["chords"]
        for where, pattern in patterns.items():
            if len(_steps(pattern)) != steps:
                raise StrudelizerError(
                    STAGE,
                    f"pattern has {len(_steps(pattern))} steps, the meter says {steps}",
                    location=f"{location}: meters.{meter}.{where}",
                    fix="write one character per step (spaces are ignored)",
                )
        meters[meter] = {
            "steps": steps,
            "drums": {d: _steps(spec["drums"][d]) for d in DRUMS if d in spec.get("drums", {})},
            "bass": _steps(spec["bass"]) if spec.get("bass") else None,
            "chords": _steps(spec["chords"]) if spec.get("chords") else None,
        }
    bass = data.get("bass", {})
    return {
        "name": data.get("name", "custom"),
        "velocity": {**DEFAULT_VELOCITY, **data.get("velocity", {})},
        "bass": {"rule": bass.get("rule", "root"), "octave": bass.get("octave", 2)},
        "meters": meters,
    }


def load_style_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StrudelizerError(STAGE, f"cannot read style: {exc.strerror}", location=str(path)) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{path} line {mark.line + 1}" if mark else str(path)
        raise StrudelizerError(STAGE, f"style is not valid YAML: {exc}", location=where) from None
    return validate_style(data or {}, location=str(path))


def _builtin(name: str) -> dict[str, Any]:
    return yaml.safe_load(resources.files(__package__).joinpath(f"{name}.yaml").read_text(encoding="utf-8"))


def lofi() -> dict[str, Any]:
    """Laid-back boom-bap drums, root-fifth bass, sustained chords."""
    return _builtin("lofi")


def rock() -> dict[str, Any]:
    """Straight 8th hats, backbeat snare, driving root bass, chords on the beat."""
    return _builtin("rock")


def four_on_floor() -> dict[str, Any]:
    """Kick on every beat, offbeat open hats and octave bass, chord stabs."""
    return _builtin("four_on_floor")

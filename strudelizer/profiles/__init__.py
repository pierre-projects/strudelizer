"""Sound profiles (FR-31): YAML files mapping roles and drums to Strudel sounds.

The built-in profiles are registered as entry points in the
`strudelizer.profiles` group, pointing at the loader functions below. A
third-party package registers its own profile the same way, with any
zero-argument callable that returns the profile mapping.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ..core.errors import StrudelizerError
from ..core.ir import DRUMS, ROLES

STAGE = "profile"

# Decision 3: IR drum name -> Strudel sample name.
DEFAULT_DRUM_MAP = {
    "kick": "bd",
    "snare": "sd",
    "closed_hat": "hh",
    "open_hat": "oh",
    "clap": "cp",
    "rim": "rim",
    "tom_low": "lt",
    "tom_mid": "mt",
    "tom_high": "ht",
    "crash": "cr",
    "ride": "rd",
    # In Strudel's default kit (uzu-drumkit) but missing from some banks
    # (TR-909 has none of them): list them under drums.unbanked there.
    "cowbell": "cb",
    "tambourine": "tb",
    "shaker": "sh",
}
DEFAULT_SOUND = "triangle"

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAMPLE = re.compile(r"^[A-Za-z0-9_.:-]+$")

PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "drums": {
            "type": "object",
            "properties": {
                "bank": {"type": "string", "pattern": _SAMPLE.pattern},
                "map": {
                    "description": "IR drum -> Strudel sample name; null drops that drum with a warning.",
                    "type": "object",
                    "propertyNames": {"enum": list(DRUMS)},
                    "additionalProperties": {
                        "anyOf": [{"type": "string", "pattern": _SAMPLE.pattern}, {"type": "null"}]
                    },
                },
                "unbanked": {
                    "description": "Drums the bank lacks; they play from Strudel's default kit, without .bank().",
                    "type": "array",
                    "items": {"enum": list(DRUMS)},
                },
                "fx": {"$ref": "#/$defs/fx"},
            },
            "additionalProperties": False,
        },
        "roles": {
            "type": "object",
            "propertyNames": {"enum": list(ROLES)},
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "sound": {"type": "string", "pattern": _SAMPLE.pattern},
                    "fx": {"$ref": "#/$defs/fx"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
    "$defs": {
        "fx": {
            "description": "Ordered Strudel effect calls, e.g. [{lpf: 800}, {room: 0.3}].",
            "type": "array",
            "items": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 1,
                "propertyNames": {"pattern": _NAME.pattern},
                "additionalProperties": {"type": ["number", "string"]},
            },
        }
    },
}


def validate_profile(data: Any, location: str = "profile") -> dict[str, Any]:
    """Check a profile mapping and fill in defaults. Returns a new dict."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import best_match

    error = best_match(Draft202012Validator(PROFILE_SCHEMA).iter_errors(data))
    if error is not None:
        path = ".".join(str(p) for p in error.absolute_path) or "(top level)"
        raise StrudelizerError(
            STAGE,
            f"invalid sound profile: {error.message}",
            location=f"{location}: {path}",
            fix="see strudelizer/profiles/default.yaml for the profile format",
        )
    drums = data.get("drums", {})
    roles = data.get("roles", {})
    return {
        "name": data.get("name", "custom"),
        "drums": {
            "bank": drums.get("bank"),
            "map": {**DEFAULT_DRUM_MAP, **drums.get("map", {})},
            "unbanked": [d for d in DRUMS if d in drums.get("unbanked", [])],
            "fx": list(drums.get("fx", [])),
        },
        "roles": {
            role: {
                "sound": roles.get(role, roles.get("other", {})).get("sound", DEFAULT_SOUND),
                "fx": list(roles.get(role, roles.get("other", {})).get("fx", [])),
            }
            for role in ROLES
            if role != "drums"
        },
    }


def load_profile_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StrudelizerError(STAGE, f"cannot read profile: {exc.strerror}", location=str(path)) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{path} line {mark.line + 1}" if mark else str(path)
        raise StrudelizerError(STAGE, f"profile is not valid YAML: {exc}", location=where) from None
    return validate_profile(data or {}, location=str(path))


def _builtin(name: str) -> dict[str, Any]:
    text = resources.files(__package__).joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def default() -> dict[str, Any]:
    """Neutral synths with a TR-909 kit."""
    return _builtin("default")


def lofi() -> dict[str, Any]:
    """Warm, filtered and roomy with a LinnDrum kit."""
    return _builtin("lofi")


def techno() -> dict[str, Any]:
    """Driving saw bass and a TR-909 kit with grit."""
    return _builtin("techno")

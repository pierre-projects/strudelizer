"""Option metadata for the generated options panel.

The registry deliberately carries no option metadata: a plugin just reads the
keys it cares about out of the `options` mapping it is handed. The UI needs
more than that to draw a control, so each option is described here as

    {name, label, type, default, help, group, choices | choices_from, ...}

with three levels of knowledge about a plugin, most specific first:

1. the plugin declares its own `options` attribute (any plugin can opt in);
2. this table knows it, because it ships with Strudelizer;
3. neither, in which case `/api/plugins` marks it `custom` and the frontend
   offers a plain key=value editor, so a newly installed plugin still works.

`label` is what a musician reads and `help` carries the technical spelling, so
the panel can show "Snap to grid" with "quantize:16+8t" in its tooltip.
"""

from __future__ import annotations

from typing import Any, Mapping

TYPES = ("number", "integer", "text", "select", "boolean")

try:  # the table describes plugins that may not be installed, so never require one
    from strudelizer.core.tab import RHYTHMS
except ImportError:
    RHYTHMS = ("even8", "even16", "columns")

# ---- shared option definitions ---------------------------------------------

BPM = {
    "name": "bpm",
    "label": "Tempo",
    "type": "number",
    "default": 100,
    "unit": "BPM",
    "min": 20,
    "max": 400,
    "step": 1,
    "group": "common",
    "help": "--bpm: a chord sheet carries no tempo, so without this it plays at 100.",
}

BEATS_PER_CHORD = {
    "name": "beats_per_chord",
    "label": "Beats per chord",
    "type": "number",
    "default": None,
    "min": 1,
    "max": 32,
    "step": 1,
    "group": "advanced",
    "placeholder": "one bar",
    "help": "--beats-per-chord: how long each chord lasts. Empty means one bar.",
}

PICKUP = {
    "name": "pickup",
    "label": "Pickup beats",
    "type": "number",
    "default": None,
    "min": 0,
    "max": 32,
    "step": 1,
    "group": "common",
    "placeholder": "none",
    "help": "--pickup: beats in a partial first bar, played before bar 1.",
}

TUNING = {
    "name": "tuning",
    "label": "Tuning",
    "type": "text",
    "default": None,
    "group": "common",
    "placeholder": "from the tab",
    "help": "Open-string notes, lowest first (EADGBE). Empty reads the tab's own labels.",
}

CAPO = {
    "name": "capo",
    "label": "Capo",
    "type": "integer",
    "default": None,
    "min": 0,
    "max": 12,
    "step": 1,
    "group": "advanced",
    "placeholder": "0",
    "help": "--capo: the fret the capo sits on; every pitch shifts up by that much.",
}

TAB_RHYTHM = {
    "name": "tab_rhythm",
    "label": "Tab rhythm",
    "type": "select",
    "default": "even8",
    "choices": list(RHYTHMS),
    "group": "common",
    "help": "--tab-rhythm: a tab carries no rhythm. even8/even16 space the columns "
            "evenly; columns fits each measure to a bar.",
}

GRID = {
    "name": "grid",
    "label": "Snap to grid",
    "type": "select",
    "default": "16+8t",
    "choices": ["4", "8", "16", "32", "8t", "16t", "16+8t", "32+16t"],
    "group": "common",
    "help": "quantize:16+8t: 8t and 16t are triplet grids; + keeps both.",
}

STYLE = {
    "name": "style",
    "label": "Groove style",
    "type": "select",
    "default": "lofi",
    "choices_from": "styles",
    "group": "common",
    "help": "arrange:style=lofi: the drums and bass to invent for a song that has none.",
}

SEMITONES = {
    "name": "semitones",
    "label": "Transpose",
    "type": "integer",
    "default": 0,
    "unit": "semitones",
    "min": -24,
    "max": 24,
    "step": 1,
    "group": "common",
    "help": "transpose:-2: shifts notes, chords and the key.",
}

SECTION_BARS = {
    "name": "bars",
    "label": "Section length",
    "type": "select",
    "default": None,
    "choices": ["2", "4", "8", "16"],
    "group": "advanced",
    "placeholder": "best fit",
    "help": "detect_sections:8: bars per block. Empty tries 16, 8, 4 then 2.",
}

DRUM_MAP = {
    "name": "map",
    "label": "Drum map file",
    "type": "text",
    "default": None,
    "group": "advanced",
    "placeholder": "kit.yaml",
    "help": "remap_drums:kit.yaml: a YAML file of `clap: snare` renames (`null` drops one).",
}

PROFILE = {
    "name": "profile",
    "label": "Sound profile",
    "type": "select",
    "default": "default",
    "choices_from": "profiles",
    "group": "common",
    "help": "--profile lofi: the Strudel sound and effects each role plays.",
}

# ---- the table --------------------------------------------------------------
#
# An entry of [] means "this plugin takes no options", which is not the same as
# having no entry at all (see `describe`). An entry for a plugin nobody has
# installed sits here harmlessly: it is only read when a plugin of that name
# turns up, and that plugin's own `options` attribute wins over it.

OPTIONS: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("importer", "midi"): [PICKUP],
    ("importer", "chordsheet"): [BPM, PICKUP, BEATS_PER_CHORD, TUNING, CAPO, TAB_RHYTHM],
    ("importer", "ascii_tab"): [BPM, PICKUP, TUNING, CAPO, TAB_RHYTHM],
    # Guitar Pro and MusicXML carry their own tempo, meter and pickup.
    ("importer", "guitarpro"): [],
    ("importer", "musicxml"): [],
    ("pass", "quantize"): [GRID],
    ("pass", "dedupe_bars"): [],
    ("pass", "arrange"): [STYLE],
    ("pass", "detect_sections"): [SECTION_BARS],
    ("pass", "transpose"): [SEMITONES],
    ("pass", "remap_drums"): [DRUM_MAP],
    ("emitter", "strudel"): [PROFILE],
    ("emitter", "midi"): [],
    ("emitter", "ir_json"): [],
}


# What to call each plugin on screen. The docstring summary stays as the
# tooltip, so "Tidy up the timing" and "quantize" are both one hover apart.
PLUGIN_LABELS = {
    ("importer", "midi"): "MIDI file",
    ("importer", "chordsheet"): "Chord sheet",
    ("importer", "ascii_tab"): "Guitar tab",
    ("importer", "guitarpro"): "Guitar Pro",
    ("importer", "musicxml"): "MusicXML",
    ("pass", "arrange"): "Add drums and bass",
    ("pass", "quantize"): "Tidy up the timing",
    ("pass", "dedupe_bars"): "Collapse repeated bars",
    ("pass", "detect_sections"): "Find sections",
    ("pass", "transpose"): "Change key",
    ("pass", "remap_drums"): "Swap drum sounds",
    ("emitter", "strudel"): "Strudel code",
    ("emitter", "midi"): "MIDI file",
    ("emitter", "ir_json"): "Song data",
}


def plugin_label(kind: str, name: str, plugin: Any) -> str:
    """A plugin's own `label`, else this table's, else its registered name."""
    declared = getattr(plugin, "label", None)
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    return PLUGIN_LABELS.get((kind, name), name)


def describe(kind: str, name: str, plugin: Any) -> list[dict[str, Any]] | None:
    """This plugin's options, or None when nobody knows them.

    None is what makes the panel fall back to a key=value editor, so a plugin
    nobody has heard of is usable rather than invisible.
    """
    declared = getattr(plugin, "options", None)
    if declared is not None:
        return [_normalise(option) for option in declared]
    return OPTIONS.get((kind, name))


def _normalise(option: Any) -> dict[str, Any]:
    """A plugin-declared option, filled out enough for the frontend to draw."""
    if isinstance(option, Mapping):
        data = dict(option)
    else:  # any object with the attributes, e.g. a dataclass
        data = {
            key: getattr(option, key)
            for key in ("name", "label", "type", "default", "help", "group", "choices",
                        "choices_from", "unit", "min", "max", "step", "placeholder")
            if getattr(option, key, None) is not None
        }
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("a plugin option needs a name")
    default = data.get("default")
    data["name"] = name
    data.setdefault("label", name.replace("_", " ").capitalize())
    data.setdefault("type", _guess_type(default, data.get("choices")))
    data.setdefault("default", default)
    data.setdefault("help", "")
    data.setdefault("group", "advanced")
    if data["type"] not in TYPES:
        data["type"] = "text"
    return data


def _guess_type(default: Any, choices: Any) -> str:
    if choices:
        return "select"
    if isinstance(default, bool):
        return "boolean"
    if isinstance(default, int):
        return "integer"
    if isinstance(default, float):
        return "number"
    return "text"

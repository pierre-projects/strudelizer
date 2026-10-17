"""General MIDI tables and track helpers shared by importers and emitters.

Importers never import each other, so the GM percussion map (used by the
MIDI, Guitar Pro and MusicXML importers and the MIDI emitter) and the track
role heuristic live here.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

# General MIDI percussion key -> IR drum vocabulary (Decision 3).
GM_DRUMS = {
    35: "kick", 36: "kick",
    37: "rim",
    38: "snare", 40: "snare",
    39: "clap",
    42: "closed_hat", 44: "closed_hat",
    46: "open_hat",
    41: "tom_low", 43: "tom_low",
    45: "tom_mid", 47: "tom_mid",
    48: "tom_high", 50: "tom_high",
    49: "crash", 52: "crash", 55: "crash", 57: "crash",
    51: "ride", 53: "ride", 59: "ride",
    56: "cowbell",
    54: "tambourine",
    69: "shaker", 70: "shaker", 82: "shaker",  # cabasa, maracas, GM2 shaker
}

# IR drum -> the GM key written for it; each maps back to the same drum.
GM_KEYS = {
    "kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46, "clap": 39, "rim": 37,
    "tom_low": 43, "tom_mid": 47, "tom_high": 50, "crash": 49, "ride": 51,
    "cowbell": 56, "tambourine": 54, "shaker": 70,
}

_ROLE_KEYWORDS = (
    ("bass", re.compile(r"bass", re.I)),
    ("vocal", re.compile(r"vocal|voice|vox|sing", re.I)),
    ("chords", re.compile(r"chord|pad|keys|piano|organ|comp|rhythm", re.I)),
    ("melody", re.compile(r"lead|melody|solo|flute|sax|trumpet", re.I)),
)


def guess_role(name: str, program: int | None, notes: Sequence[tuple]) -> str:
    """Role for a pitched track. `notes` are (start, end, pitch, ...) tuples.

    First match wins: a name keyword, GM program 32-39 (basses), a median
    pitch below C3, at least 2 notes sounding on average at each onset
    (chords), else melody.
    """
    for role, pattern in _ROLE_KEYWORDS:
        if pattern.search(name):
            return role
    if program is not None and 32 <= program <= 39:
        return "bass"
    pitches = sorted(n[2] for n in notes)
    if pitches and pitches[len(pitches) // 2] < 48:
        return "bass"
    onsets = sorted({n[0] for n in notes})
    if onsets:
        sounding = sum(sum(1 for n in notes if n[0] <= t < n[1]) for t in onsets)
        if sounding / len(onsets) >= 2:
            return "chords"
    return "melody"


def slug(text: str) -> str:
    """'Synth Bass 2' -> 'synth_bass_2', valid as an IR track id."""
    value = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if value and value[0].isdigit():
        value = "t_" + value
    return value


def unique_ids(bases: Iterable[str]) -> list[str]:
    """['bass', 'bass', 'gtr'] -> ['bass', 'bass_2', 'gtr']."""
    used: dict[str, int] = {}
    out = []
    for base in bases:
        count = used.get(base, 0) + 1
        used[base] = count
        out.append(base if count == 1 else f"{base}_{count}")
    return out

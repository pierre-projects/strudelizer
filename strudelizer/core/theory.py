"""Small music-theory helpers. Pitches are MIDI numbers; c4 = 60.

Chord symbols (Decision 2) are parsed here into the IR's canonical form:
root, quality, extensions, bass. The grammar is strict, a token is a chord
only if it is root + a known spelling + optional /bass, so lyrics are not
mistaken for chords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NOTE_NAMES = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")

_LETTERS = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def midi_to_name(pitch: int) -> str:
    """60 -> 'c4', 61 -> 'c#4', 21 -> 'a0'."""
    octave, chroma = divmod(pitch, 12)
    return f"{NOTE_NAMES[chroma]}{octave - 1}"


def name_to_midi(name: str) -> int:
    """'c4' -> 60, 'Eb3' -> 51, 'f#-1' -> 6."""
    text = name.strip().lower()
    if not text or text[0] not in _LETTERS:
        raise ValueError(f"not a note name: {name!r}")
    value = _LETTERS[text[0]]
    i = 1
    while i < len(text) and text[i] in "#b":
        value += 1 if text[i] == "#" else -1
        i += 1
    octave = int(text[i:]) if text[i:] else 3
    return value + (octave + 1) * 12


# ---- pitch classes and spelling ---------------------------------------------------

SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

_ROOT = re.compile(r"^([A-G])([#b♯♭]?)")


def pitch_class(note: str) -> int:
    """'C' -> 0, 'F#' -> 6, 'Bb' -> 10, 'Cb' -> 11."""
    match = _ROOT.match(note)
    if not match or match.end() != len(note):
        raise ValueError(f"not a note: {note!r}")
    letter, accidental = match.groups()
    value = _LETTERS[letter.lower()]
    if accidental in ("#", "♯"):
        value += 1
    elif accidental in ("b", "♭"):
        value -= 1
    return value % 12


def spell(pc: int, flats: bool) -> str:
    return (FLAT_NAMES if flats else SHARP_NAMES)[pc % 12]


# Keys conventionally written with flats (major roots; minor keys use their
# relative major). Everything else is spelled with sharps.
_FLAT_MAJOR = {0: False, 1: True, 2: False, 3: True, 4: False, 5: True, 6: False,
               7: False, 8: True, 9: False, 10: True, 11: False}

_KEY = re.compile(r"^([A-G][#b♯♭]?)\s*(m|min|minor|maj|major)?$", re.I)


def parse_key(key: str) -> tuple[int, bool] | None:
    """'F#m' -> (6, True minor); 'Bb' -> (10, False). None if unreadable."""
    match = _KEY.match(key.strip())
    if not match:
        return None
    root = match.group(1)
    root = root[0].upper() + root[1:]
    minor = (match.group(2) or "").lower() in ("m", "min", "minor")
    return pitch_class(root), minor


def key_prefers_flats(key: str | None) -> bool:
    parsed = parse_key(key) if key else None
    if parsed is None:
        return False
    pc, minor = parsed
    major = (pc + 3) % 12 if minor else pc
    return _FLAT_MAJOR[major]


def format_key(pc: int, minor: bool) -> str:
    major = (pc + 3) % 12 if minor else pc
    return spell(pc, _FLAT_MAJOR[major]) + ("m" if minor else "")


# ---- chords --------------------------------------------------------------------------

# spelling (text after the root) -> (quality, extensions). Decision 2 lists the
# required spellings; a few common extras are accepted too.
_SPELLINGS: dict[str, tuple[str, tuple[str, ...]]] = {}


def _alias(quality: str, extensions: tuple[str, ...], *spellings: str) -> None:
    for s in spellings:
        _SPELLINGS[s] = (quality, extensions)


_alias("maj", (), "", "maj", "M")
_alias("m", (), "m", "min", "-", "mi")
_alias("7", (), "7", "dom7")
_alias("maj7", (), "maj7", "M7", "^7", "^", "Δ", "Δ7", "ma7")
_alias("m7", (), "m7", "min7", "-7", "mi7")
_alias("6", (), "6")
_alias("m6", (), "m6", "min6", "-6")
_alias("7", ("9",), "9")
_alias("maj", ("add9",), "add9", "add2")
_alias("m", ("add9",), "madd9", "madd2")
_alias("sus2", (), "sus2")
_alias("sus4", (), "sus4", "sus")
_alias("7sus4", (), "7sus4", "7sus")
_alias("dim", (), "dim", "°", "o")
_alias("dim7", (), "dim7", "°7", "o7")
_alias("m7b5", (), "m7b5", "ø", "ø7", "min7b5", "-7b5", "m7(b5)")
_alias("aug", (), "aug", "+", "+5")
_alias("maj7", ("9",), "maj9", "M9", "^9", "Δ9")
_alias("m7", ("9",), "m9", "min9", "-9")
_alias("6", ("9",), "69", "6/9")
_alias("7", ("11",), "11")
_alias("7", ("13",), "13")
_alias("7", ("b9",), "7b9")
_alias("7", ("#9",), "7#9")
_alias("mmaj7", (), "mmaj7", "m^7", "mM7", "m(maj7)", "-^7")
_alias("5", (), "5")

# canonical (quality, extensions) -> short name, used by emitters to look up
# their own spelling. Unknown combinations fall back to quality+extensions.
_NAMES = {
    ("maj", ()): "",
    ("m", ()): "m",
    ("7", ()): "7",
    ("maj7", ()): "maj7",
    ("m7", ()): "m7",
    ("6", ()): "6",
    ("m6", ()): "m6",
    ("7", ("9",)): "9",
    ("maj", ("add9",)): "add9",
    ("m", ("add9",)): "madd9",
    ("sus2", ()): "sus2",
    ("sus4", ()): "sus4",
    ("7sus4", ()): "7sus4",
    ("dim", ()): "dim",
    ("dim7", ()): "dim7",
    ("m7b5", ()): "m7b5",
    ("aug", ()): "aug",
    ("maj7", ("9",)): "maj9",
    ("m7", ("9",)): "m9",
    ("6", ("9",)): "69",
    ("7", ("11",)): "11",
    ("7", ("13",)): "13",
    ("7", ("b9",)): "7b9",
    ("7", ("#9",)): "7#9",
    ("mmaj7", ()): "mmaj7",
    ("5", ()): "5",
}

# short name -> intervals above the root, in semitones
_INTERVALS = {
    "": (0, 4, 7),
    "m": (0, 3, 7),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "m7": (0, 3, 7, 10),
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "9": (0, 4, 7, 10, 14),
    "add9": (0, 4, 7, 14),
    "madd9": (0, 3, 7, 14),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "7sus4": (0, 5, 7, 10),
    "dim": (0, 3, 6),
    "dim7": (0, 3, 6, 9),
    "m7b5": (0, 3, 6, 10),
    "aug": (0, 4, 8),
    "maj9": (0, 4, 7, 11, 14),
    "m9": (0, 3, 7, 10, 14),
    "69": (0, 4, 7, 9, 14),
    "11": (0, 7, 10, 14, 17),
    "13": (0, 4, 10, 14, 21),
    "7b9": (0, 4, 7, 10, 13),
    "7#9": (0, 4, 7, 10, 15),
    "mmaj7": (0, 3, 7, 11),
    "5": (0, 7),
}

CHORD_ROOT_OCTAVE_BASE = 48  # roots voiced from C3 (48) to B3 (59)
CHORD_BASS_OCTAVE_BASE = 36  # slash bass notes from C2 (36) to B2 (47)

_CHORD = re.compile(r"^([A-G][#b♯♭]?)(.*?)(?:/([A-G][#b♯♭]?))?$")


@dataclass(frozen=True)
class ChordSpelling:
    root: str
    quality: str
    extensions: tuple[str, ...]
    bass: str | None

    @property
    def name(self) -> str:
        """Short canonical name of quality+extensions, e.g. 'maj7', '9'."""
        return chord_name(self.quality, self.extensions)

    def pitches(self, with_bass: bool = True) -> tuple[int, ...]:
        return chord_pitches(self.root, self.quality, self.extensions, self.bass if with_bass else None)


def _norm_note(note: str) -> str:
    return note.replace("♯", "#").replace("♭", "b")


def split_symbol(token: str) -> tuple[str, str, str | None] | None:
    """'Bbmaj7/D' -> ('Bb', 'maj7', 'D'): root, spelling as written, bass."""
    token = token.strip()
    if not token:
        return None
    # "6/9" contains a slash that is not a bass note
    if "6/9" in token:
        head, _, rest = token.partition("6/9")
        match = _CHORD.match(head + "\0" + rest)
        if not match:
            return None
        root, suffix, bass = match.groups()
        return root, suffix.replace("\0", "6/9"), bass
    match = _CHORD.match(token)
    return match.groups() if match else None  # type: ignore[return-value]


def parse_chord(token: str) -> ChordSpelling | None:
    """'Cmaj7' -> ChordSpelling('C', 'maj7', (), None); None if not a chord."""
    parts = split_symbol(token)
    if parts is None:
        return None
    root, suffix, bass = parts
    spelling = _SPELLINGS.get(suffix)
    if spelling is None:
        return None
    quality, extensions = spelling
    return ChordSpelling(_norm_note(root), quality, extensions, _norm_note(bass) if bass else None)


def chord_name(quality: str, extensions: tuple[str, ...] | None) -> str:
    extensions = tuple(extensions or ())
    name = _NAMES.get((quality, extensions))
    return name if name is not None else quality + "".join(extensions)


def chord_pitches(
    root: str, quality: str, extensions: tuple[str, ...] | None, bass: str | None = None
) -> tuple[int, ...]:
    """A plain close voicing: root in octave 3, the slash bass (if any) in
    octave 2 below it. Raises ValueError for unknown qualities."""
    intervals = _INTERVALS.get(chord_name(quality, extensions))
    if intervals is None:
        raise ValueError(f"no voicing for quality {quality!r} {extensions or ()}")
    base = CHORD_ROOT_OCTAVE_BASE + pitch_class(root)
    pitches = [base + i for i in intervals]
    if bass is not None:
        pitches.insert(0, CHORD_BASS_OCTAVE_BASE + pitch_class(bass))
    return tuple(pitches)


def is_no_chord(token: str) -> bool:
    return token.upper().rstrip(".") in ("N.C", "NC", "N.C.")


def transpose_note(note: str, semitones: int, flats: bool) -> str:
    return spell(pitch_class(note) + semitones, flats)

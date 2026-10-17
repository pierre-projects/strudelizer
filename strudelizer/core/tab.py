"""ASCII tablature parsing (FR-13), shared by the tab and chord sheet importers.

A tab block is 4 to 7 consecutive staff lines, highest string first:

    e|-------0---|
    B|-----1-----|
    G|---2-------|
    D|-2---------|
    A|-----------|
    E|-----------|  x2

String labels set the tuning (each label's pitch class, in the octave
closest to standard tuning for that string count), else --tuning or
standard tuning is used. A capo adds semitones to every fret. Fret numbers
are kept; technique symbols (h p b r / \\ ~ ^ ( ) < > s t =) are ignored,
and x (dead/muted note) is dropped. A trailing `x2` after the last bar line
repeats the block.

Rhythm (a tab has none):
    even8   every column with a note is one eighth note (default)
    even16  every column with a note is one sixteenth note
    columns the position within a measure (between | bar lines) sets the
            time; a block without bar lines is one measure. Use the quantize
            pass to tidy the result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

from .theory import pitch_class

RHYTHMS = ("even8", "even16", "columns")

# open-string pitches, lowest string first
STANDARD_TUNINGS = {
    4: (28, 33, 38, 43),               # bass: E1 A1 D2 G2
    5: (23, 28, 33, 38, 43),           # 5-string bass: B0 E1 A1 D2 G2
    6: (40, 45, 50, 55, 59, 64),       # guitar: E2 A2 D3 G3 B3 E4
    7: (35, 40, 45, 50, 55, 59, 64),   # 7-string guitar: B1 + standard
}

NAMED_TUNINGS = {
    "standard": "E A D G B E",
    "drop d": "D A D G B E",
    "drop c": "C G C F A D",
    "half step down": "Eb Ab Db Gb Bb Eb",
    "eb": "Eb Ab Db Gb Bb Eb",
    "d standard": "D G C F A D",
    "open g": "D G D G B D",
    "open d": "D A D F# A D",
    "open e": "E B E G# B E",
    "dadgad": "D A D G A D",
}

_LABEL = re.compile(r"^([A-Ga-g][#b]?)\s*(?=[|:\-])")
_BODY_CHARS = set("-0123456789|:hpbrtsxX/\\~^().<>=* ")
_REPEAT_TAIL = re.compile(r"^(.*\|)\s*\(?\s*(?:[xX]\s*(\d+)|(\d+)\s*[xX])\s*\)?\s*$")
_NOTE_NAME = re.compile(r"^([A-Ga-g][#b]?)(-?\d+)?$")


class TabError(ValueError):
    """A tuning or option that cannot be used; the message says why."""


@dataclass
class StaffLine:
    lineno: int
    label: str | None
    body: str
    repeat: int = 1


@dataclass
class TabNote:
    start: Fraction  # beats from the start of the tab
    duration: Fraction
    pitch: int


@dataclass
class TabResult:
    notes: list[TabNote] = field(default_factory=list)
    length: Fraction = Fraction(0)  # beats used, from 0
    strings: int = 0
    problems: list[tuple[int, str, str]] = field(default_factory=list)  # (lineno, line, reason)


def staff_line(text: str, lineno: int = 0) -> StaffLine | None:
    """Parse one line as a tab staff line, or None if it is not one."""
    line = text.strip()
    if not line:
        return None
    label = None
    match = _LABEL.match(line)
    if match:
        label = match.group(1)
        line = line[match.end():]
    elif line[0] not in "|:-":
        return None
    repeat = 1
    tail = _REPEAT_TAIL.match(line)
    if tail:
        line = tail.group(1)
        repeat = int(tail.group(2) or tail.group(3))
    if not set(line) <= _BODY_CHARS:
        return None
    # "G|--5h7|" is clearly a staff line; without a string label, ask for
    # more dashes so prose with a hyphen or two is not mistaken for one
    labelled = label is not None and line[:1] in "|:"
    if line.count("-") < (1 if labelled else 3):
        return None
    return StaffLine(lineno, label, line.rstrip(), repeat)


def looks_like_staff(text: str) -> bool:
    """Loose test used to report broken staff lines: mostly dashes."""
    line = text.strip()
    return line.count("-") >= 6 and line.count("-") >= len(line) / 2


def find_blocks(lines: list[tuple[int, str]]) -> list[list[StaffLine]]:
    """Group consecutive staff lines. Blocks of any size are returned; the
    caller decides what a valid string count is."""
    blocks: list[list[StaffLine]] = []
    current: list[StaffLine] = []
    for lineno, text in lines:
        staff = staff_line(text, lineno)
        if staff is not None:
            current.append(staff)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_tuning(text: str, strings: int) -> tuple[int, ...]:
    """'D A D G B E' (lowest first), 'drop d', or 'D2 A2 D3 G3 B3 E4'."""
    spec = NAMED_TUNINGS.get(text.strip().lower(), text)
    tokens = spec.replace(",", " ").split()
    if len(tokens) == 1 and len(tokens[0]) > 1 and all(c.isalpha() or c in "#b" for c in tokens[0]):
        tokens = re.findall(r"[A-Ga-g][#b]?", tokens[0])  # "DADGBE"
    if len(tokens) != strings:
        raise TabError(f"tuning {text!r} has {len(tokens)} notes for a {strings}-string tab")
    pitches = []
    for i, token in enumerate(tokens):
        match = _NOTE_NAME.match(token)
        if not match:
            raise TabError(f"{token!r} in tuning {text!r} is not a note name")
        name = match.group(1)[0].upper() + match.group(1)[1:]
        if match.group(2) is not None:
            pitches.append(pitch_class(name) + (int(match.group(2)) + 1) * 12)
        else:
            pitches.append(_nearest(pitch_class(name), _standard(strings)[i]))
    return tuple(pitches)


def _standard(strings: int) -> tuple[int, ...]:
    if strings in STANDARD_TUNINGS:
        return STANDARD_TUNINGS[strings]
    raise TabError(f"no standard tuning for {strings} strings (4 to 7 are supported)")


def _nearest(pc: int, reference: int) -> int:
    """The pitch with pitch class `pc` closest to `reference` (ties go down)."""
    base = reference - ((reference - pc) % 12)
    return base if reference - base <= 6 else base + 12


def tuning_from_labels(labels: list[str]) -> tuple[int, ...]:
    """Staff labels top (highest) first -> open-string pitches lowest first."""
    low_first = list(reversed(labels))
    std = _standard(len(low_first))
    return tuple(_nearest(pitch_class(l[0].upper() + l[1:]), std[i]) for i, l in enumerate(low_first))


def parse_block(
    block: list[StaffLine],
    tuning: tuple[int, ...] | None,
    capo: int,
    rhythm: str,
    bar_beats: Fraction,
    step: Fraction,
    start: Fraction,
) -> tuple[list[TabNote], Fraction, list[tuple[int, str, str]]]:
    """Notes of one block (times from `start`), the block's length, problems.

    `tuning` overrides the labels when given. `step` is the even-rhythm slot
    length in beats; `bar_beats` is a measure in `columns` mode.
    """
    problems: list[tuple[int, str, str]] = []
    strings = len(block)
    if tuning is not None:
        open_strings = tuning
    elif all(s.label for s in block):
        open_strings = tuning_from_labels([s.label for s in block])  # type: ignore[misc]
    else:
        open_strings = _standard(strings)
    width = max(len(s.body) for s in block)
    for s in block:
        if width - len(s.body) > 2:
            problems.append((s.lineno, s.body, "staff line is shorter than the others in its block"))
    bodies = [s.body.ljust(width, "-") for s in block]
    # string index 0 is the top line = highest string
    events: dict[int, list[int]] = {}
    for row, body in enumerate(bodies):
        open_pitch = open_strings[strings - 1 - row]
        for match in re.finditer(r"\d+", body):
            fret = int(match.group())
            if fret > 30:
                problems.append((block[row].lineno, body, f"fret {fret} is out of range"))
                continue
            events.setdefault(match.start(), []).append(open_pitch + fret + capo)
        # a dead note (x) keeps its rhythmic slot but makes no sound
        for match in re.finditer(r"[xX]", body):
            events.setdefault(match.start(), [])
    bars = [c for c in range(width) if all(b[c] in "|:" for b in bodies)]
    columns = sorted(events)

    if rhythm in ("even8", "even16"):
        times = {c: start + i * step for i, c in enumerate(columns)}
        length = len(columns) * step
        ends = {c: times[c] + step for c in columns}
        for a, b in zip(columns, columns[1:]):
            ends[a] = times[b]
    else:  # columns: position inside each measure
        edges = sorted(set([-1] + bars + [width]))
        measures = [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 1]
        measures = [(a, b) for a, b in measures if any(a < c < b for c in columns)] or measures[:1]
        times, ends = {}, {}
        for m, (a, b) in enumerate(measures):
            inside = [c for c in columns if a < c < b]
            span = b - a - 1
            m_start = start + m * bar_beats
            for c in inside:
                times[c] = m_start + Fraction(c - a - 1, span) * bar_beats
            for c, nxt in zip(inside, inside[1:] + [None]):
                ends[c] = times[nxt] if nxt is not None else m_start + bar_beats
        length = len(measures) * bar_beats

    notes = [
        TabNote(times[c], ends[c] - times[c], pitch)  # dead-note columns have no pitches
        for c in columns if c in times
        for pitch in sorted(set(events[c]))
    ]
    repeat = max(s.repeat for s in block)
    out = []
    for r in range(repeat):
        shift = r * length
        out += [TabNote(n.start + shift, n.duration, n.pitch) for n in notes]
    return out, length * repeat, problems


def tab_role(strings: int, notes: list) -> tuple[str, str]:
    """(track id, role) for tab notes (anything with .start): 4-5 strings is
    a bass; otherwise chords when 2+ notes start together on average, else
    melody."""
    if strings in (4, 5):
        return "bass", "bass"
    onsets = sorted({n.start for n in notes})
    if onsets:
        together = sum(sum(1 for n in notes if n.start == t) for t in onsets) / len(onsets)
        if together >= 2:
            return "guitar", "chords"
    return "guitar", "melody"


def parse_tab(
    lines: list[tuple[int, str]],
    *,
    tuning: str | None = None,
    capo: int = 0,
    rhythm: str = "even8",
    bar_beats: Fraction = Fraction(4),
    beat_unit: int = 4,
    start: Fraction = Fraction(0),
) -> TabResult:
    """Every tab block in `lines`, one after another in time."""
    if rhythm not in RHYTHMS:
        raise TabError(f"unknown tab rhythm {rhythm!r}; use one of {', '.join(RHYTHMS)}")
    # an eighth or sixteenth note in beats of the time signature's unit
    step = Fraction(beat_unit, 8 if rhythm == "even8" else 16)
    result = TabResult()
    time = start
    for block in find_blocks(lines):
        if not 4 <= len(block) <= 7:
            for s in block:
                result.problems.append(
                    (s.lineno, s.body, f"a tab block needs 4 to 7 strings, this one has {len(block)}")
                )
            continue
        open_strings = parse_tuning(tuning, len(block)) if tuning else None
        notes, length, problems = parse_block(block, open_strings, capo, rhythm, bar_beats, step, time)
        result.notes += notes
        result.problems += problems
        result.strings = max(result.strings, len(block))
        time += length
    result.length = time - start
    staff_numbers = {s.lineno for b in find_blocks(lines) for s in b}
    for lineno, text in lines:
        if lineno not in staff_numbers and looks_like_staff(text):
            result.problems.append((lineno, text.strip(), "looks like a tab line but has characters a tab cannot have"))
    result.problems.sort()
    return result

"""ASCII tab importer (FR-13): guitar and bass tabs in plain text.

Reads `.tab` files, and `.txt` files that are mostly tab staff lines (a
chord sheet with a few tab blocks is left to the chordsheet importer, which
imports the blocks itself). Block parsing and rhythm rules are in
core.tab. Header lines set metadata:

    Title: Rust Belt Riff
    Tuning: D A D G B E      (or "Drop D"; lowest string first)
    Capo: 2
    Tempo: 120               (also "BPM: 120")
    Time: 3/4

Options (CLI flags): tuning (--tuning), capo (--capo), tab_rhythm
(--tab-rhythm even8 | even16 | columns), bpm (--bpm), pickup (--pickup).
"""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.ir import Meta, Note, Song, Track
from ..core.tab import TabError, find_blocks, parse_tab, tab_role
from ..registry import Importer

STAGE = "import:ascii_tab"
DEFAULT_BPM = 100

_HEADER = re.compile(r"^\s*(title|song|tuning|capo|tempo|bpm|time|time signature)\s*[:=]?\s*(.+?)\s*$", re.I)


def read_text(path: Path, stage: str) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise StrudelizerError(stage, "file not found", location=str(path)) from None
    except OSError as exc:
        raise StrudelizerError(stage, f"cannot read file: {exc.strerror}", location=str(path)) from None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        warn(stage, f"{path.name} is not UTF-8; read it as Latin-1")
        return data.decode("latin-1")


class AsciiTabImporter(Importer):
    """ASCII guitar/bass tabs (.tab, or .txt that is mostly tab): 4 to 7 strings."""

    name = "ascii_tab"
    extensions = (".tab", ".txt")

    def can_handle(self, path: str | Path) -> bool:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".tab":
            return True
        if suffix != ".txt":
            return False
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return False
        lines = [(i, l) for i, l in enumerate(text.splitlines(), 1) if l.strip()]
        staff = sum(len(b) for b in find_blocks(lines) if 4 <= len(b) <= 7)
        return staff >= 4 and staff * 2 >= len(lines)

    def load(self, path: str | Path, options: Mapping[str, Any]) -> Song:
        path = Path(path)
        text = read_text(path, STAGE)
        lines = list(enumerate(text.splitlines(), 1))
        headers: dict[str, str] = {}
        staff_lines = {s.lineno for b in find_blocks(lines) for s in b}
        for lineno, line in lines:
            if lineno in staff_lines:
                continue
            match = _HEADER.match(line)
            if match:
                key = match.group(1).lower().replace("time signature", "time").replace("song", "title")
                headers.setdefault("bpm" if key == "tempo" else key, match.group(2))

        meter = (4, 4)
        if "time" in headers:
            m = re.match(r"^(\d+)\s*/\s*(\d+)$", headers["time"])
            if m and int(m.group(2)) in (1, 2, 4, 8, 16, 32):
                meter = (int(m.group(1)), int(m.group(2)))
            else:
                warn(STAGE, f"ignored time signature {headers['time']!r}; using 4/4")
        tuning = options.get("tuning") or headers.get("tuning")
        if tuning and tuning.strip().lower() == "standard":
            tuning = None  # labels or the standard tuning for the string count
        capo = _int_option(options.get("capo", headers.get("capo", 0)), "capo")
        rhythm = str(options.get("tab_rhythm") or "even8")
        try:
            result = parse_tab(
                lines,
                tuning=tuning,
                capo=capo,
                rhythm=rhythm,
                bar_beats=Fraction(meter[0]),
                beat_unit=meter[1],
            )
        except TabError as exc:
            raise StrudelizerError(STAGE, str(exc), location=str(path),
                                   fix='e.g. --tuning "D A D G B E" (lowest string first) or --tab-rhythm even16') from None
        for lineno, line, reason in result.problems:
            warn(STAGE, f"line {lineno}: skipped unparsed line {line!r}: {reason}")
        if not result.notes:
            raise StrudelizerError(
                STAGE, "no tab notes found", location=str(path),
                fix="write tab blocks of 4 to 7 staff lines like e|---0---|",
            )
        notes = [Note(n.start, n.duration, n.pitch) for n in result.notes]
        bpm = options.get("bpm")
        if bpm is None and "bpm" in headers:
            try:
                bpm = float(headers["bpm"])
            except ValueError:
                warn(STAGE, f"ignored tempo {headers['bpm']!r}")
        if bpm is None:
            bpm = DEFAULT_BPM
            warn(STAGE, f"no tempo in the tab; using {DEFAULT_BPM} bpm (pass --bpm or add 'Tempo: N')")
        bpm = float(bpm)
        pickup = None
        if options.get("pickup") is not None:
            pickup = Fraction(str(options["pickup"])) or None
        track_id, role = tab_role(result.strings, notes)
        return Song(
            meta=Meta(
                title=headers.get("title") or path.stem,
                bpm=int(bpm) if bpm.is_integer() else bpm,
                time_signature=meter,
                source=path.name,
                pickup_beats=pickup,
            ),
            tracks=(Track(events=tuple(notes), id=track_id, role=role,
                          instrument="gm:33" if role == "bass" else "gm:25"),),
        )


def _int_option(value: Any, name: str) -> int:
    try:
        number = int(str(value).strip())
        assert 0 <= number <= 24
        return number
    except (ValueError, AssertionError):
        raise StrudelizerError(STAGE, f"{name} must be a whole number of frets from 0 to 24, not {value!r}",
                               location=f"option {name}", fix=f"e.g. --{name} 2") from None

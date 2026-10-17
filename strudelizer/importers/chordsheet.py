"""Chord sheet importer (FR-11).

Reads three notations, line by line, in any mix:

a) ChordPro: inline chords `[Am]lyrics [F]more`, directives `{title: ..}`,
   `{key: ..}`, `{tempo: ..}`, `{time: 3/4}`, `{start_of_chorus}` / `{soc}`
   and friends, `{chorus}` to repeat the last chorus.
b) Chords over lyrics: a line made only of chord tokens, usually above a
   lyric line. Tokens must parse exactly (core.theory.parse_chord), so
   lyrics are never read as chords.
c) Bar lines: `| Am | F | C G |`. Chords in one bar split it evenly; `/`
   or `.` holds the previous chord for one slot, `%` repeats the previous
   bar, an empty bar holds the chord, `|: ... :|` repeats, a trailing `x2`
   repeats the line.

In (a) and (b) each chord lasts `beats_per_chord` beats (default one bar).
Section labels: `[Verse]`, `Chorus:`, `Bridge 2:` or ChordPro's
`{start_of_*}` directives. A pickup (partial first bar) is declared with
`{pickup: 1}` (or `{x_pickup: 1}`) or the --pickup option: the first chord
(or first bar) then lasts that many beats.

Every line that looks like it was meant to hold chords but does not parse
is reported as a warning with its line number, and skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.ir import Chord, Meta, Section, Song, Track
from ..core.theory import ChordSpelling, is_no_chord, parse_chord
from ..registry import Importer

STAGE = "import:chordsheet"
DEFAULT_BPM = 100

_DIRECTIVE = re.compile(r"^\{\s*([A-Za-z_][\w-]*)\s*(?::\s*(.*?))?\s*\}$")
_BRACKET_LINE = re.compile(r"^\[([^\]]+)\]:?$")
_INLINE = re.compile(r"\[([^\]]*)\]")
_KNOWN_LABEL = (
    r"intro|verse|pre-?chorus|chorus|bridge|outro|solo|interlude|instrumental|"
    r"tag|coda|refrain|hook|break|ending|turnaround|vamp"
)
_WORD_LABEL = re.compile(rf"^({_KNOWN_LABEL})(\s*\d+)?\s*(:\s*(.*))?$", re.I)
_REPEAT = re.compile(r"^\(?\s*(?:x\s*(\d+)|(\d+)\s*x)\s*\)?$", re.I)
_CHORDISH = re.compile(r"^[A-H][#b♯♭]?[\w#♯♭°ø+\-^Δ()/]*$")
_BAR_SPLIT = re.compile(r"(\|:|:\||\|\||\|)")

_START = {
    "start_of_chorus": "chorus", "soc": "chorus",
    "start_of_verse": "verse", "sov": "verse",
    "start_of_bridge": "bridge", "sob": "bridge",
    "start_of_grid": None, "sog": None,  # grids hold bar lines: no section
}
_END = {"end_of_chorus", "eoc", "end_of_verse", "eov", "end_of_bridge", "eob", "end_of_grid", "eog"}
_TAB_START = {"start_of_tab", "sot"}
_TAB_END = {"end_of_tab", "eot"}
_IGNORED = {
    "subtitle", "st", "artist", "composer", "lyricist", "album", "year", "copyright",
    "comment", "c", "comment_italic", "ci", "comment_box", "cb", "highlight", "capo",
    "duration", "meta", "textfont", "textsize", "chordfont", "chordsize", "define", "chord",
}


def _section_name(label: str) -> str:
    """'Verse 2' -> 'verse_2'; 'Pre-Chorus' -> 'pre_chorus'."""
    name = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "section"
    return f"s_{name}" if name[0].isdigit() else name


def _chordish(token: str) -> bool:
    """Looks like an attempt at a chord: starts with a note letter and has a
    digit or a chord symbol character in it (so 'Bad' or 'Day' do not)."""
    return bool(_CHORDISH.match(token)) and (
        parse_chord(token) is not None or any(c in token for c in "0123456789#♯♭°ø+^Δ/")
    )


@dataclass
class _Event:
    start: Fraction
    duration: Fraction
    chord: ChordSpelling
    symbol: str


@dataclass
class _OpenSection:
    name: str
    start_bar: int
    start_time: Fraction
    event_index: int


@dataclass
class _Parser:
    path: Path
    options: Mapping[str, Any]
    events: list[_Event] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    time: Fraction = Fraction(0)
    meter: tuple[int, int] = (4, 4)
    title: str | None = None
    first_text: str | None = None
    key: str | None = None
    tempo: float | None = None
    pickup: Fraction | None = None
    pickup_pending: bool = False
    started: bool = False  # a chord or bar has been placed
    open: _OpenSection | None = None
    last_chorus: tuple[list[_Event], Fraction] | None = None
    unparsed: int = 0
    in_tab: bool = False  # inside {start_of_tab} ... {end_of_tab}

    # ---- time line -------------------------------------------------------------

    @property
    def bar_len(self) -> Fraction:
        return Fraction(self.meter[0])

    @property
    def offset(self) -> Fraction:
        return self.bar_len - self.pickup if self.pickup else Fraction(0)

    def beats_per_chord(self) -> Fraction:
        value = self.options.get("beats_per_chord")
        if value is None:
            return self.bar_len
        try:
            beats = Fraction(str(value))
        except (ValueError, ZeroDivisionError):
            beats = Fraction(0)
        if beats <= 0:
            raise StrudelizerError(
                STAGE, f"beats per chord must be a positive number, not {value!r}",
                location="option beats_per_chord", fix="e.g. --beats-per-chord 2",
            )
        return beats

    def _begin(self) -> None:
        if not self.started:
            self.started = True
            self.pickup_pending = bool(self.pickup)

    def unit(self, normal: Fraction) -> Fraction:
        """Length of the next chord/bar: the pickup for the very first one."""
        self._begin()
        if self.pickup_pending:
            self.pickup_pending = False
            return self.pickup  # type: ignore[return-value]
        return normal

    def add(self, chord: ChordSpelling | None, symbol: str, beats: Fraction) -> None:
        if chord is not None:
            self.events.append(_Event(self.time, beats, chord, symbol))
        self.time += beats

    def hold(self, beats: Fraction) -> None:
        """Extend the chord that is sounding (or the rest) by `beats`."""
        if self.events and self.events[-1].start + self.events[-1].duration == self.time:
            self.events[-1].duration += beats
        self.time += beats

    def align(self) -> None:
        """Move to the next bar line, holding the current chord."""
        if not self.started:
            return
        into_bar = (self.time + self.offset) % self.bar_len
        if into_bar:
            self.hold(self.bar_len - into_bar)

    def bar_index(self) -> int:
        return int((self.time + self.offset) // self.bar_len)

    # ---- sections --------------------------------------------------------------

    def start_section(self, name: str) -> None:
        self.end_section()
        self.align()
        self.open = _OpenSection(name, self.bar_index(), self.time, len(self.events))

    def end_section(self) -> None:
        if self.open is None:
            return
        self.align()
        length = self.bar_index() - self.open.start_bar
        if length > 0:
            self.sections.append(Section(self.open.start_bar, length, self.open.name))
            if self.open.name.startswith("chorus"):
                body = [
                    _Event(e.start - self.open.start_time, e.duration, e.chord, e.symbol)
                    for e in self.events[self.open.event_index:]
                ]
                self.last_chorus = (body, self.time - self.open.start_time)
        self.open = None

    def recall_chorus(self, label: str | None, lineno: int) -> None:
        if self.last_chorus is None:
            self.report(lineno, "{chorus}", "there is no earlier chorus to repeat")
            return
        self.start_section(_section_name(label) if label else "chorus")
        self._begin()
        body, length = self.last_chorus
        for e in body:
            self.events.append(_Event(self.time + e.start, e.duration, e.chord, e.symbol))
        self.time += length
        self.end_section()

    # ---- reporting ---------------------------------------------------------------

    def report(self, lineno: int, line: str, reason: str) -> None:
        self.unparsed += 1
        warn(STAGE, f"line {lineno}: skipped unparsed line {line.strip()!r}: {reason}")

    # ---- line handlers -------------------------------------------------------------

    def directive(self, name: str, value: str | None, lineno: int, line: str) -> None:
        name = name.lower().replace("-", "_")
        if name in ("title", "t"):
            self.title = value or self.title
        elif name == "key":
            self.key = value or None
        elif name == "tempo":
            try:
                self.tempo = float(value or "")
                assert self.tempo > 0
            except (ValueError, AssertionError):
                self.report(lineno, line, "tempo must be a positive number")
        elif name == "time":
            match = re.match(r"^(\d+)\s*/\s*(\d+)$", value or "")
            if not match or int(match.group(2)) not in (1, 2, 4, 8, 16, 32):
                self.report(lineno, line, "time must look like 3/4 or 6/8")
            elif self.started:
                self.report(lineno, line, "time signature changes are not supported yet; "
                                          "put {time} before the first chord")
            else:
                self.meter = (int(match.group(1)), int(match.group(2)))
        elif name in ("pickup", "x_pickup"):
            if self.options.get("pickup") is None:  # the --pickup option wins
                self.set_pickup(value, f"line {lineno}")
        elif name in _START:
            section = _START[name]
            if section is not None:
                self.start_section(_section_name(value) if value else section)
        elif name in _END:
            self.end_section()
        elif name == "chorus":
            self.recall_chorus(value, lineno)
        elif name in _IGNORED or name.startswith("x_"):
            pass
        elif name in ("new_song", "ns"):
            self.report(lineno, line, "only one song per file is supported")
        else:
            self.report(lineno, line, f"unknown directive {{{name}}}")

    def set_pickup(self, value: Any, where: str) -> None:
        if self.started:
            raise StrudelizerError(STAGE, "a pickup must be declared before the first chord", location=where)
        try:
            beats = Fraction(str(value))
        except (ValueError, ZeroDivisionError):
            beats = Fraction(-1)
        if beats == 0:
            self.pickup = None
            return
        if not 0 < beats < self.bar_len:
            raise StrudelizerError(
                STAGE, f"pickup must be between 0 and {self.bar_len} beats, not {value!r}",
                location=where, fix="a pickup is a partial first bar, e.g. {pickup: 1}",
            )
        self.pickup = beats

    def chord_tokens(self, tokens: list[str]) -> tuple[list[tuple[ChordSpelling | None, str]], list[str]]:
        """Parsed (chord or None for N.C.) and the tokens that failed."""
        good, bad = [], []
        for token in tokens:
            if is_no_chord(token):
                good.append((None, token))
            else:
                chord = parse_chord(token)
                if chord is None:
                    bad.append(token)
                else:
                    good.append((chord, token))
        return good, bad

    def chord_line(self, tokens: list[str], repeat: int) -> None:
        good, _ = self.chord_tokens(tokens)
        for _ in range(repeat):
            for chord, token in good:
                self.add(chord, token, self.unit(self.beats_per_chord()))

    def bar_line(self, text: str, lineno: int, line: str) -> None:
        tokens = text.split()
        repeat = 1
        if tokens and _REPEAT.match(tokens[-1]):
            m = _REPEAT.match(tokens[-1])
            repeat = int(m.group(1) or m.group(2))
            text = text[: text.rfind(tokens[-1])]
        parts = [p.strip() for p in _BAR_SPLIT.split(text)]
        seen_bar_line = False
        bars: list[list[str]] = []
        current: list[str] | None = None  # None: before the first bar line
        repeat_from: int | None = None
        for part in parts:
            if part in ("|", "||", "|:", ":|"):
                # an empty bar counts only between two bar lines, not before
                # the first one ("| C |" starts with an empty text segment)
                if current is not None and (current or seen_bar_line):
                    bars.append(current)
                seen_bar_line = True
                current = []
                if part == "|:":
                    repeat_from = len(bars)
                elif part == ":|":
                    start = repeat_from if repeat_from is not None else 0
                    bars.extend([list(b) for b in bars[start:]])
                    repeat_from = None
                continue
            if current is None:
                current = []  # text before the first bar line
            current.extend(part.split())
        if current:
            bars.append(current)
        bad = []
        for bar in bars:
            for token in bar:
                if token in ("/", ".", "%") or is_no_chord(token) or parse_chord(token):
                    continue
                bad.append(token)
        if bad or not bars:
            reason = f"not chords: {', '.join(repr(b) for b in bad)}" if bad else "no bars found"
            self.report(lineno, line, reason)
            return
        self.align()
        previous: list[str] = []
        for _ in range(repeat):
            for bar in bars:
                if bar == ["%"]:
                    bar = previous
                length = self.unit(self.bar_len)
                if not bar:
                    self.hold(length)
                    continue
                slot = length / len(bar)
                for token in bar:
                    if token in ("/", "."):
                        self.hold(slot)
                    elif is_no_chord(token):
                        self.add(None, token, slot)
                    else:
                        self.add(parse_chord(token), token, slot)
                previous = bar

    def inline_line(self, line: str, lineno: int) -> None:
        good: list[tuple[ChordSpelling | None, str]] = []
        bad = []
        for content in _INLINE.findall(line):
            content = content.strip()
            if content.startswith("*"):
                continue  # ChordPro annotation, not a chord
            if is_no_chord(content):
                good.append((None, content))
            elif (chord := parse_chord(content)) is not None:
                good.append((chord, content))
            else:
                bad.append(content)
        if bad:
            self.report(lineno, line, f"not chords: {', '.join(f'[{b}]' for b in bad)}")
            return
        for chord, token in good:
            self.add(chord, token, self.unit(self.beats_per_chord()))

    def line(self, raw: str, lineno: int) -> None:
        line = raw.strip()
        if not line or line.startswith("#"):
            return
        directive = _DIRECTIVE.match(line)
        if directive:
            self.directive(directive.group(1), directive.group(2), lineno, line)
            return
        bracket = _BRACKET_LINE.match(line)
        if bracket:
            content = bracket.group(1).strip()
            if not (parse_chord(content) or is_no_chord(content) or content.startswith("*")):
                self.start_section(_section_name(content))
                return
        word = _WORD_LABEL.match(line)
        if word:
            label = word.group(1) + (word.group(2) or "")
            self.start_section(_section_name(label))
            rest = (word.group(4) or "").strip()
            if rest:
                self.line(rest, lineno)
            return
        if "|" in line:
            self.bar_line(line, lineno, line)
            return
        if _INLINE.search(line):
            self.inline_line(line, lineno)
            return
        tokens = line.split()
        repeat = 1
        if len(tokens) > 1 and _REPEAT.match(tokens[-1]):
            m = _REPEAT.match(tokens[-1])
            repeat = int(m.group(1) or m.group(2))
            tokens = tokens[:-1]
        good, bad = self.chord_tokens(tokens)
        if not bad:
            self.chord_line(tokens, repeat)
            return
        if good and all(_chordish(t) for t in bad):
            self.report(lineno, line, f"not chords: {', '.join(repr(b) for b in bad)}")
            return
        # a lyric (or other text) line
        if self.first_text is None and not self.started and self.open is None:
            self.first_text = line

    # ---- result ----------------------------------------------------------------------

    def song(self, text: str) -> Song:
        if self.options.get("pickup") is not None:
            self.set_pickup(self.options["pickup"], "option pickup")
        for lineno, raw in enumerate(text.splitlines(), 1):
            if self.in_tab:
                d = _DIRECTIVE.match(raw.strip())
                if d and d.group(1).lower() in _TAB_END:
                    self.in_tab = False
                continue
            d = _DIRECTIVE.match(raw.strip())
            if d and d.group(1).lower() in _TAB_START:
                self.in_tab = True  # tabs are a later phase (P3): skip the block
                warn(STAGE, f"line {lineno}: skipped a tab block (tabs are not read from chord sheets)")
                continue
            self.line(raw, lineno)
        self.end_section()
        if not self.events:
            raise StrudelizerError(
                STAGE, "no chords found", location=str(self.path),
                fix="write chords as [C] (ChordPro), on their own line, or as | C | G | bars",
            )
        bpm = self.options.get("bpm")
        if bpm is None:
            bpm = self.tempo
        if bpm is None:
            bpm = DEFAULT_BPM
            warn(STAGE, f"no tempo in the sheet; using {DEFAULT_BPM} bpm (pass --bpm or add {{tempo: N}})")
        bpm = float(bpm)
        if bpm <= 0:
            raise StrudelizerError(STAGE, f"bpm must be positive, not {bpm}", location="option bpm")
        events = tuple(
            Chord(
                e.start,
                e.duration,
                e.symbol,
                root=e.chord.root,
                quality=e.chord.quality,
                extensions=e.chord.extensions or None,
                bass=e.chord.bass,
                pitches=e.chord.pitches(),
            )
            for e in self.events
        )
        return Song(
            meta=Meta(
                title=self.title or self.first_text or self.path.stem,
                bpm=int(bpm) if bpm.is_integer() else bpm,
                time_signature=self.meter,
                key=self.key,
                source=self.path.name,
                pickup_beats=self.pickup,
            ),
            sections=tuple(self.sections),
            tracks=(Track(events=events, id="chords", role="chords"),),
        )


class ChordSheetImporter(Importer):
    """Chord sheets: ChordPro, chords over lyrics, or | bar | lines | (.cho, .crd, .txt)."""

    name = "chordsheet"
    extensions = (".cho", ".crd", ".chopro", ".chordpro", ".pro", ".txt")

    def load(self, path: str | Path, options: Mapping[str, Any]) -> Song:
        path = Path(path)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise StrudelizerError(STAGE, "file not found", location=str(path)) from None
        except OSError as exc:
            raise StrudelizerError(STAGE, f"cannot read file: {exc.strerror}", location=str(path)) from None
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
            warn(STAGE, f"{path.name} is not UTF-8; read it as Latin-1")
        return _Parser(path, options).song(text)

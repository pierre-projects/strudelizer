"""Strudel emitter (FR-30).

All Strudel syntax in Strudelizer lives in this file. Output was checked
against the pinned Strudel runtime (@strudel/* 1.2.6, see tests/strudel).

Layout of the generated code:
- one bar = one cycle, `setcps(bpm / 60 / beatsPerBar)` (Decision 4);
- each track is one pattern, `"<bar0 bar1 ...>"`, with one mini-notation
  bar per cycle; repeated bars collapse to `bar!n`, and a track whose
  bars repeat with a period that divides the song is written once;
- tracks are joined with `stack(...)`; songs with sections get one
  `const` per section joined with `arrange(...)`.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping, Sequence

from .. import __version__
from ..core.errors import StrudelizerError, warn
from ..core.ir import DRUMS, Chord, Hit, Note, Section, Song, Track
from ..core.theory import chord_name, midi_to_name
from ..core.time import (
    DEFAULT_BPM,
    bar_offset,
    beats_per_bar,
    lcm_denominator,
    slice_bars,
    song_length_bars,
    time_signature,
)
from ..registry import Emitter

STAGE = "emit:strudel"
EXPAND_RESTS_UP_TO = 16  # write `~ ~ ~` on grids up to 16 steps, `~@3` beyond
BARS_PER_LINE = 4
INDENT = "  "

# Canonical chord name (core.theory.chord_name of quality + extensions,
# Decision 2) -> suffix in Strudel's voicing dictionary, each checked against
# the pinned @strudel/tonal. Chords missing here, and all slash chords, are
# written as explicit note stacks from the chord's `pitches`.
CHORD_SUFFIX = {
    "": "",
    "maj": "",
    "m": "m",
    "min": "m",
    "7": "7",
    "maj7": "^7",
    "m7": "m7",
    "6": "6",
    "m6": "m6",
    "69": "69",
    "9": "9",
    "maj9": "^9",
    "m9": "m9",
    "add9": "add9",
    "11": "11",
    "13": "13",
    "7b9": "7b9",
    "sus4": "sus",
    "sus": "sus",
    "7sus4": "7sus",
    "dim": "o",
    "dim7": "o7",
    "m7b5": "h7",
    "aug": "aug",
    "mmaj7": "m^7",
    "madd9": "madd9",
    "7#9": "7#9",
    "5": "5",
    "sus2": "2",  # the dictionary's "2" voices root, 2nd, 5th (no third)
}
_STRUDEL_SUFFIXES = sorted(set(CHORD_SUFFIX.values()), key=len, reverse=True)
_SYMBOL = re.compile(r"^([A-G](?:#|b)?)(.*)$")

# Names a section const must not shadow.
_RESERVED = {
    "arguments", "await", "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "enum", "eval", "export", "extends", "false", "finally",
    "for", "function", "if", "implements", "import", "in", "instanceof", "interface", "let",
    "new", "null", "package", "private", "protected", "public", "return", "static", "super",
    "switch", "this", "throw", "true", "try", "typeof", "var", "void", "while", "with", "yield",
    "arrange", "cat", "chord", "n", "note", "s", "seq", "setcps", "silence", "sound", "stack",
}


@dataclass(frozen=True)
class _Item:
    start: Fraction  # beats from bar start
    length: Fraction | None  # None for drum hits (one grid step)
    token: str
    velocity: int | None


@dataclass(frozen=True)
class _Kind:
    """One sub-pattern of a track: drum hits, notes, or chord symbols."""

    func: str  # s / note / chord
    bars: list[dict[Any, list[_Item]]]  # per bar: voice key -> items
    keys: list[Any]  # every voice key, in output order
    banked: bool = False  # drums: add the profile's .bank()
    # Velocities that set the scale: every hit of the track, so drums split
    # into banked and unbanked patterns stay relative to each other.
    pool: tuple[int | None, ...] | None = None


class StrudelEmitter(Emitter):
    """Strudel live-coding JavaScript (.js) that plays on strudel.cc."""

    name = "strudel"
    extension = ".js"

    def emit(self, song: Song, options: Mapping[str, Any]) -> str:
        profile = options.get("profile") or "default"
        if not isinstance(profile, Mapping):
            from ..registry import get_profile

            profile = get_profile(str(profile))
        return _Writer(song, profile).write()


class _Writer:
    def __init__(self, song: Song, profile: Mapping[str, Any]) -> None:
        self.song = song
        self.profile = profile
        self.bar_len = beats_per_bar(song.meta)
        self.offset = bar_offset(song.meta)  # pickup: bar 1 starts on cycle 1
        self.n_bars = song_length_bars(song)
        self.dropped: dict[str, int] = defaultdict(int)
        if song.sections:
            self.n_bars = max(self.n_bars, max(s.start_bar + s.length for s in song.sections))
        numbered = [(i, t) for i, t in enumerate(song.tracks) if t.events]
        self.tracks = [t for _, t in numbered]
        self.track_names = [_track_name(t, i) for i, t in numbered]
        self.ids = [self._bar_ids(t, name) for t, name in zip(self.tracks, self.track_names)]
        self.kinds = [self._kinds(t, name) for t, name in zip(self.tracks, self.track_names)]
        if self.dropped:
            detail = ", ".join(f"{d} x{n}" for d, n in sorted(self.dropped.items()))
            warn(STAGE, f"profile '{profile.get('name', 'custom')}' has no sound for these drums, dropped: {detail}")

    def _bar_label(self, index: int) -> str:
        if self.offset:
            return "the pickup bar" if index == 0 else f"bar {index}"
        return f"bar {index + 1}"

    # ---- top level ---------------------------------------------------------

    def write(self) -> str:
        meta = self.song.meta
        num = time_signature(meta)[0]
        bpm = meta.bpm if meta.bpm is not None else DEFAULT_BPM
        lines = [
            f"// {_comment(meta.title or 'Untitled')}",
            f"// Source: {_comment(meta.source or 'unknown')}",
            f"// Generated by Strudelizer {__version__} (profile: {_comment(str(self.profile.get('name', 'custom')))})",
        ]
        if self.offset:
            beats = _num(float(meta.pickup_beats)) if meta.pickup_beats.denominator != 1 else str(meta.pickup_beats)
            lines.append(f"// Pickup: {beats} beat(s) at the end of cycle 0; bar 1 starts on cycle 1")
        lines += [f"setcps({_num(bpm)}/60/{num})", ""]
        if self.song.sections:
            lines += self._write_sections()
        else:
            lines.append(self._stack(range(self.n_bars), INDENT))
        return "\n".join(lines) + "\n"

    def _write_sections(self) -> list[str]:
        out: list[str] = []
        consts: dict[str, str] = {}  # const name -> body
        order: list[tuple[int, str]] = []
        for index, section in enumerate(_fill_sections(self.song.sections, self.n_bars)):
            bars = range(section.start_bar, section.start_bar + section.length)
            body = self._stack(bars, INDENT)
            base = _const_name(section.name or f"part{index + 1}")
            name, n = base, 1
            while name in consts and consts[name] != body:
                n += 1
                name = f"{base}_{n}"
            if name not in consts:
                consts[name] = body
                out += [f"const {name} = {body}", ""]
            order.append((section.length, name))
        joined = f",\n{INDENT}".join(f"[{length}, {name}]" for length, name in order)
        out.append(f"arrange(\n{INDENT}{joined}\n)")
        return out

    def _stack(self, bars: range, indent: str) -> str:
        entries = []
        for t_index, track in enumerate(self.tracks):
            pattern = self._track_pattern(t_index, bars, indent)
            if pattern is None:
                continue
            label = f"{self.track_names[t_index]} ({track.role or 'other'})"
            entries.append((t_index, f"{indent}// {_comment(label)}\n{indent}{pattern}"))
        if not entries:
            return "silence"
        if len(entries) == 1:  # no stack needed; lay the pattern out at top level
            return self._track_pattern(entries[0][0], bars, "") or "silence"
        return "stack(\n" + ",\n".join(text for _, text in entries) + "\n)"

    # ---- per track -------------------------------------------------------------

    def _bar_ids(self, track: Track, name: str) -> list[int] | None:
        if track.bars is None:
            return None
        bars = list(track.bars)
        if len(bars) != self.n_bars or any(b > i or bars[b] != b for i, b in enumerate(bars)):
            raise StrudelizerError(
                STAGE,
                f"the `bars` list has {len(bars)} entries for a {self.n_bars}-bar song, or points forward",
                location=f"track {name}",
                fix="re-run the dedupe_bars pass after any pass that changes events",
            )
        return bars

    def _kinds(self, track: Track, name: str) -> list[_Kind]:
        hits = [e for e in track.events if isinstance(e, Hit)]
        notes = [e for e in track.events if isinstance(e, Note)]
        symbols: list[Chord] = []
        for event in track.events:
            if not isinstance(event, Chord):
                continue
            if _chord_symbol(event) is not None:
                symbols.append(event)
            elif event.pitches:
                notes += [Note(event.start, event.duration, p) for p in event.pitches]
            else:
                index = math.floor((event.start + self.offset) / self.bar_len)
                raise StrudelizerError(
                    STAGE,
                    f"chord '{event.symbol}' has no Strudel voicing and no pitches",
                    location=f"track {name}, {self._bar_label(index)}",
                    fix="add `pitches` to the chord event, or use a quality Strudel's voicing "
                    f"dictionary knows: {', '.join(k for k in CHORD_SUFFIX if k) }",
                )
        kinds = []
        if hits:
            drums = self.profile["drums"]
            drum_map = drums["map"]
            playable = []
            for hit in hits:
                if drum_map.get(hit.drum) is None:
                    self.dropped[hit.drum] += 1
                else:
                    playable.append(hit)
            # Drums the bank lacks play from Strudel's default kit, so they
            # live in their own s() pattern without .bank().
            unbanked = set(drums.get("unbanked", ())) if drums.get("bank") else set(DRUMS)
            for banked in (True, False):
                group = [h for h in playable if (h.drum not in unbanked) == banked]
                if not group:
                    continue
                bars = []
                for bar in self._slice(group):
                    voices: dict[Any, list[_Item]] = defaultdict(list)
                    for hit in bar:
                        voice = voices[hit.drum]
                        if not voice or voice[-1].start != hit.start:
                            voice.append(_Item(hit.start, None, drum_map[hit.drum], hit.velocity))
                    bars.append(dict(voices))
                keys = [d for d in DRUMS if any(d in b for b in bars)]
                pool = tuple(h.velocity for h in playable)
                kinds.append(_Kind("s", bars, keys, banked=banked and bool(drums.get("bank")), pool=pool))
        if notes:
            bars = [_note_voices(bar) for bar in self._slice(notes)]
            kinds.append(_Kind("note", bars, _int_keys(bars)))
        if symbols:
            bars = [_chord_voices(bar) for bar in self._slice(symbols)]
            kinds.append(_Kind("chord", bars, _int_keys(bars)))
        return kinds

    def _slice(self, events: Sequence[Any]) -> list[tuple[Any, ...]]:
        return slice_bars(events, self.bar_len, self.n_bars, self.offset)

    def _track_pattern(self, t_index: int, bars: range, indent: str) -> str | None:
        track = self.tracks[t_index]
        ids = self.ids[t_index]
        local_ids = _local_ids(ids, bars)
        parts = []
        for kind in self.kinds[t_index]:
            pattern = self._kind_pattern(track, kind, bars, local_ids, indent)
            if pattern is not None:
                parts.append(pattern)
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        inner = indent + INDENT
        return "stack(\n" + ",\n".join(inner + _reindent(p, INDENT) for p in parts) + f"\n{indent})"

    def _kind_pattern(
        self, track: Track, kind: _Kind, bars: range, ids: list[int] | None, indent: str
    ) -> str | None:
        section = [kind.bars[i] for i in bars]
        if not any(section):
            return None
        velocities = _velocity_scale(kind)
        suffix = self._sound(track, kind)
        voicing = ".voicing()" if kind.func == "chord" else ""

        if velocities is None:
            bar_strings = [_render_bar(b, kind.keys, self.bar_len) for b in section]
            mini = _sequence(bar_strings, ids, indent)
            return f"{kind.func}({mini}){voicing}{suffix}"

        # Velocities vary: one pattern per voice so each can carry its own
        # step-aligned .velocity() pattern without duplicating events.
        voices = []
        inner = indent + INDENT
        for key in kind.keys:
            per_bar = [b.get(key, []) for b in section]
            if not any(per_bar):
                continue
            values = _sequence([_render_voice(items, self.bar_len) for items in per_bar], ids, inner)
            levels = {velocities[i.velocity] for items in per_bar for i in items}
            pattern = f"{kind.func}({values}){voicing}"
            if len(levels) == 1:
                level = levels.pop()
                if level != "1":
                    pattern += f".velocity({level})"
            else:
                vel_bars = [
                    _render_voice([_Item(i.start, i.length, velocities[i.velocity], None) for i in items], self.bar_len)
                    for items in per_bar
                ]
                pattern += f".velocity({_sequence(vel_bars, ids, inner)})"
            voices.append(pattern)
        if len(voices) == 1:
            return voices[0] + suffix
        return "stack(\n" + ",\n".join(inner + v for v in voices) + f"\n{indent}){suffix}"

    def _sound(self, track: Track, kind: _Kind) -> str:
        if kind.func == "s":
            drums = self.profile["drums"]
            out = f".bank({_str(drums['bank'])})" if kind.banked else ""
            fx = drums.get("fx", [])
        else:
            role = track.role if track.role in self.profile["roles"] else "other"
            spec = self.profile["roles"][role]
            out = f".s({_str(spec['sound'])})"
            fx = spec.get("fx", [])
        for effect in fx:
            ((name, value),) = effect.items()
            out += f".{name}({_str(value) if isinstance(value, str) else _num(value)})"
        return out


# ---- voices and bars --------------------------------------------------------------


def _int_keys(bars: list[dict[Any, list[_Item]]]) -> list[int]:
    return list(range(max((len(b) for b in bars), default=0)))


def _note_voices(bar: Sequence[Note]) -> dict[Any, list[_Item]]:
    """Group simultaneous equal-length notes into one stacked token, then
    split the tokens into non-overlapping voices (first fit)."""
    groups: dict[tuple[Fraction, Fraction], list[Note]] = defaultdict(list)
    for note in bar:
        groups[(note.start, note.duration)].append(note)
    tokens = []
    for (start, duration), notes in groups.items():
        pitches = sorted({n.pitch for n in notes})
        names = [midi_to_name(p) for p in pitches]
        token = names[0] if len(names) == 1 else "[" + ",".join(names) + "]"
        loudest = max((n.velocity for n in notes if n.velocity is not None), default=None)
        tokens.append(_Item(start, duration, token, loudest))
    tokens.sort(key=lambda i: (i.start, i.token))
    return _first_fit(tokens)


def _chord_voices(bar: Sequence[Chord]) -> dict[Any, list[_Item]]:
    items = sorted(
        (_Item(c.start, c.duration, _chord_symbol(c) or c.symbol, None) for c in bar),
        key=lambda i: (i.start, i.token),
    )
    return _first_fit(items)


def _first_fit(items: list[_Item]) -> dict[Any, list[_Item]]:
    voices: list[list[_Item]] = []
    for item in items:
        for voice in voices:
            last = voice[-1]
            if last.start + (last.length or 0) <= item.start:
                voice.append(item)
                break
        else:
            voices.append([item])
    return {i: v for i, v in enumerate(voices)}


def _chord_symbol(chord: Chord) -> str | None:
    """The chord in Strudel's voicing-dictionary spelling, or None."""
    if chord.bass is not None:
        return None  # slash chords cannot be voiced from the dictionary
    if chord.root is not None and chord.quality is not None:
        suffix = CHORD_SUFFIX.get(chord_name(chord.quality, chord.extensions))
        return None if suffix is None else chord.root + suffix
    match = _SYMBOL.match(chord.symbol)
    if match and match.group(2) in _STRUDEL_SUFFIXES:
        return chord.symbol
    return None


def _render_voice(items: Sequence[_Item], bar_len: Fraction) -> str:
    """One voice of one bar as mini-notation steps, on the smallest grid."""
    if not items:
        return "~"
    points = [i.start / bar_len for i in items]
    points += [(i.start + i.length) / bar_len for i in items if i.length is not None]
    steps = lcm_denominator(points)
    out: list[str] = []
    pos = 0

    def rest(count: int) -> None:
        if count <= 0:
            return
        if steps <= EXPAND_RESTS_UP_TO:
            out.extend(["~"] * count)
        else:
            out.append("~" if count == 1 else f"~@{count}")

    for item in items:
        at = int(item.start / bar_len * steps)
        rest(at - pos)
        width = 1 if item.length is None else int(item.length / bar_len * steps)
        out.append(item.token if width == 1 else f"{item.token}@{width}")
        pos = at + width
    rest(steps - pos)
    if len(out) > 1 and len(set(out)) == 1 and out[0] != "~" and "@" not in out[0]:
        return f"{out[0]}*{len(out)}"
    return " ".join(out)


def _render_bar(bar: Mapping[Any, list[_Item]], keys: Sequence[Any], bar_len: Fraction) -> str:
    voices = [_render_voice(bar[k], bar_len) for k in keys if bar.get(k)]
    return ", ".join(voices) if voices else "~"


def _wrap(bar: str) -> str:
    """Bracket a bar for use as one step of `<...>` unless it already is one."""
    depth = 0
    for char in bar:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif depth == 0 and char in " ,":
            return f"[{bar}]"
    return bar


def _period(ids: Sequence[int]) -> int:
    n = len(ids)
    for p in range(1, n + 1):
        if n % p == 0 and all(ids[i] == ids[i % p] for i in range(n)):
            return p
    return n


def _local_ids(ids: list[int] | None, bars: range) -> list[int] | None:
    """Bar ids renumbered within a range of bars (a section)."""
    if ids is None:
        return None
    first: dict[int, int] = {}
    return [first.setdefault(ids[b], i) for i, b in enumerate(bars)]


def _sequence(bar_strings: Sequence[str], ids: Sequence[int] | None, indent: str) -> str:
    """A quoted mini-notation string with one bar per cycle.

    `ids` is the track's dedupe_bars map (None: dedupe did not run, write
    every bar). Bars equal in the track are equal in each of its voices, but
    a single voice can repeat more often than the whole track (a crash only
    in bar 1 should not stop the hi-hats collapsing), so repeats are found
    per rendered sequence, refining the track map.
    """
    if ids is None:
        items = [_wrap(b) for b in bar_strings]
    else:
        ids = [bar_strings.index(b) for b in bar_strings]
        p = _period(ids)
        items = []
        i = 0
        while i < p:
            j = i
            while j + 1 < p and ids[j + 1] == ids[i]:
                j += 1
            count = j - i + 1
            items.append(_wrap(bar_strings[i]) + (f"!{count}" if count > 1 else ""))
            i = j + 1
    if len(items) == 1 and "!" not in items[0]:
        return _str(bar_strings[0])  # the whole track is one repeating bar
    if len(items) <= BARS_PER_LINE:
        return _str("<" + " ".join(items) + ">")
    rows = [" ".join(items[k : k + BARS_PER_LINE]) for k in range(0, len(items), BARS_PER_LINE)]
    body = "\n".join(f"{indent}{INDENT}{row}" for row in rows)
    return f"`<\n{body}\n{indent}>`"


def _velocity_scale(kind: _Kind) -> dict[int | None, str] | None:
    """Velocity -> Strudel velocity text, relative to the loudest event, or
    None when every event in this sub-pattern has the same velocity."""
    if kind.pool is not None:
        values = set(kind.pool)
    else:
        values = {i.velocity for bar in kind.bars for items in bar.values() for i in items}
    known = {v for v in values if v is not None}
    if len(known) <= 1:
        return None
    top = max(known)
    scale: dict[int | None, str] = {None: "1"}
    for v in known:
        scale[v] = _num(round(v / top, 2))
    return scale


def _fill_sections(sections: Sequence[Section], n_bars: int) -> list[Section]:
    """Sorted sections with gaps filled, so arrange() covers the song."""
    ordered = sorted(sections, key=lambda s: s.start_bar)
    out: list[Section] = []
    pos = 0
    for section in ordered:
        if section.start_bar < pos:
            raise StrudelizerError(
                STAGE,
                f"section '{section.name}' overlaps the previous section",
                location=f"bar {section.start_bar + 1}",
                fix="make sections start where the previous one ends",
            )
        if section.start_bar > pos:
            out.append(Section(pos, section.start_bar - pos, None))
        out.append(section)
        pos = section.start_bar + section.length
    if pos < n_bars:
        out.append(Section(pos, n_bars - pos, None))
    return out


# ---- formatting -----------------------------------------------------------------


def _track_name(track: Track, index: int) -> str:
    return track.id or f"track{index + 1}"


def _const_name(name: str) -> str:
    return f"{name}_part" if name in _RESERVED else name


def _comment(text: str) -> str:
    return " ".join(text.split())


def _num(value: float | int) -> str:
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers here")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return repr(value) if isinstance(value, float) else str(value)


def _str(text: str) -> str:
    """A double-quoted JS string (Strudel parses these as mini-notation)."""
    return json.dumps(text, ensure_ascii=False)


def _reindent(text: str, extra: str) -> str:
    return text.replace("\n", "\n" + extra)

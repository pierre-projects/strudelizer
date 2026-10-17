"""Exact time handling (FR-4) and bar arithmetic.

IR times are beats, where one beat is the time signature's denominator unit
(an eighth note in 7/8). A bar is therefore always `numerator` beats long.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import replace
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Iterable, Sequence

if TYPE_CHECKING:
    from .ir import Event, Meta, Song


def parse_frac(value: str | int | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("booleans are not times")
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(value)


def format_frac(value: Fraction) -> str:
    """Fraction(3, 2) -> '3/2', Fraction(2) -> '2'."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


DEFAULT_TIME_SIGNATURE = (4, 4)
DEFAULT_BPM = 120


def time_signature(meta: "Meta") -> tuple[int, int]:
    return tuple(meta.time_signature) if meta.time_signature else DEFAULT_TIME_SIGNATURE  # type: ignore[return-value]


def beats_per_bar(meta: "Meta") -> Fraction:
    return Fraction(time_signature(meta)[0])


def bar_offset(meta: "Meta") -> Fraction:
    """Beats of silence to put before time 0 so bar lines fall on multiples
    of the bar length: with a 1-beat pickup in 4/4 this is 3, so the pickup
    fills the end of bar index 0 and bar 1 (the first full bar) starts at
    index 1. Zero without a pickup."""
    if not meta.pickup_beats:
        return Fraction(0)
    return beats_per_bar(meta) - meta.pickup_beats


def dominant(changes: list[tuple[Any, Any]], default: Any, end: Any) -> tuple[Any, bool]:
    """Decision 4's rule for tempo and meter: the value in force for the
    longest time wins (earliest on ties). `changes` are (time, value) in any
    time unit. Returns (value, whether other values were also used)."""
    changes = sorted(changes, key=lambda c: c[0])
    timeline: list[tuple[Any, Any]] = []
    if not changes or changes[0][0] > 0:
        timeline.append((0, default))
    for time, value in changes:
        if timeline and timeline[-1][0] == time:
            timeline[-1] = (time, value)
        else:
            timeline.append((time, value))
    coverage: dict[Any, Any] = {}
    first_seen: dict[Any, Any] = {}
    for i, (time, value) in enumerate(timeline):
        nxt = timeline[i + 1][0] if i + 1 < len(timeline) else max(end, time)
        coverage[value] = coverage.get(value, 0) + (nxt - time)
        first_seen.setdefault(value, time)
    used = [v for v, c in coverage.items() if c > 0] or [timeline[0][1]]
    best = max(used, key=lambda v: (coverage.get(v, 0), -first_seen[v]))
    return best, len(used) > 1


def event_end(event: "Event") -> Fraction:
    duration = getattr(event, "duration", None)
    return event.start + duration if duration is not None else event.start


def song_length_bars(song: "Song") -> int:
    """Number of bars needed to hold every event (at least 1). With a pickup,
    bar index 0 is the partial pickup bar."""
    bar = beats_per_bar(song.meta)
    offset = bar_offset(song.meta)
    bars = 2 if offset else 1
    for track in song.tracks:
        for event in track.events:
            start = event.start + offset
            end = event_end(event) + offset
            if end > start:
                bars = max(bars, math.ceil(end / bar))
            else:
                bars = max(bars, math.floor(start / bar) + 1)
    return bars


def slice_bars(
    events: Iterable["Event"], bar_len: Fraction, n_bars: int, offset: Fraction = Fraction(0)
) -> list[tuple["Event", ...]]:
    """Cut a track's events into bars, with times relative to each bar start.

    `offset` (see bar_offset) shifts every event later so a pickup lands at
    the end of bar 0. Events with a duration that cross a bar line are
    split; the part in the next bar starts at 0 (it is re-attacked). Both
    dedupe_bars and the Strudel emitter use this, so two bars with equal
    slices always render identically.
    """
    from .ir import sort_events

    bars: list[list["Event"]] = [[] for _ in range(n_bars)]
    for event in events:
        duration = getattr(event, "duration", None)
        if duration is None:
            start = event.start + offset
            index = math.floor(start / bar_len)
            if 0 <= index < n_bars:
                bars[index].append(replace(event, start=start - index * bar_len))
            continue
        start = event.start + offset
        end = start + duration
        index = math.floor(start / bar_len)
        while start < end and index < n_bars:
            bar_start = index * bar_len
            bar_end = bar_start + bar_len
            seg_end = min(end, bar_end)
            if index >= 0:
                bars[index].append(
                    replace(event, start=start - bar_start, duration=seg_end - start)
                )
            start = seg_end
            index += 1
    return [tuple(sort_events(bar)) for bar in bars]


def slice_spans(
    events: Iterable["Event"], starts: Sequence[Fraction], ends: Sequence[Fraction]
) -> list[tuple["Event", ...]]:
    """Like slice_bars, for consecutive spans [starts[i], ends[i]) of any
    length (in event time). Times come back relative to each span's start;
    events crossing a span boundary are split there."""
    from .ir import sort_events

    out: list[list["Event"]] = [[] for _ in starts]
    for event in events:
        duration = getattr(event, "duration", None)
        if duration is None:
            i = bisect.bisect_right(starts, event.start) - 1
            if 0 <= i < len(starts) and event.start < ends[i]:
                out[i].append(replace(event, start=event.start - starts[i]))
            continue
        start, end = event.start, event.start + duration
        i = max(bisect.bisect_right(starts, start) - 1, 0)
        while start < end and i < len(starts):
            seg_end = min(end, ends[i])
            if seg_end > start and start >= starts[i]:
                out[i].append(replace(event, start=start - starts[i], duration=seg_end - start))
                start = seg_end
            i += 1
    return [tuple(sort_events(seg)) for seg in out]


def song_bars(song: "Song", track_events: Iterable["Event"]) -> list[tuple["Event", ...]]:
    """slice_bars with the song's bar length, length and pickup offset."""
    return slice_bars(track_events, beats_per_bar(song.meta), song_length_bars(song), bar_offset(song.meta))


def lcm_denominator(values: Sequence[Fraction]) -> int:
    result = 1
    for value in values:
        result = result * value.denominator // math.gcd(result, value.denominator)
    return result

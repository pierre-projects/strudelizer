"""quantize pass (FR-20): snap event times to a rhythmic grid."""

from __future__ import annotations

import math
import re
from dataclasses import replace
from fractions import Fraction
from typing import Any, Mapping

from ..core.errors import StrudelizerError
from ..core.ir import Chord, Hit, Note, Song, Track
from ..core.time import bar_offset, time_signature
from ..registry import Pass

STAGE = "pass:quantize"
DEFAULT_GRID = "16+8t"
_TOKEN = re.compile(r"^(1|2|4|8|16|32|64)(t?)$")


def parse_grid(grid: Any, den: int) -> list[Fraction]:
    """'16+8t' -> grid steps in IR beats (denominator units), finest last."""
    steps = []
    for token in str(grid).replace(" ", "").split("+"):
        match = _TOKEN.match(token)
        if not match:
            raise StrudelizerError(
                STAGE,
                f"unknown grid '{token}'",
                location=f"option grid={grid!r}",
                fix="use 4, 8, 16, 32, 8t or 16t, or combine with +, e.g. quantize:16+8t",
            )
        step = Fraction(den, int(match.group(1)))  # a whole note is `den` beats
        if match.group(2):
            step *= Fraction(2, 3)
        steps.append(step)
    return steps


def snap(value: Fraction, steps: list[Fraction]) -> tuple[Fraction, Fraction]:
    """Nearest grid point over all grids, plus the step it came from.

    Ties go to the earlier point, then to the coarser grid listed first.
    """
    best: tuple[Fraction, Fraction, Fraction] | None = None
    for step in steps:
        point = math.floor(value / step + Fraction(1, 2)) * step
        candidate = (abs(value - point), point, step)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    assert best is not None
    return best[1], best[2]


class Quantize(Pass):
    """Snap starts and ends to a grid: 8, 16, 32, 8t, 16t, or combined like 16+8t."""

    name = "quantize"
    default_option = "grid"

    def run(self, song: Song, options: Mapping[str, Any]) -> Song:
        den = time_signature(song.meta)[1]
        steps = parse_grid(options.get("grid", DEFAULT_GRID), den)
        offset = bar_offset(song.meta)  # grids line up with bar lines, also after a pickup
        return replace(song, tracks=tuple(self._track(t, steps, offset) for t in song.tracks))

    def _track(self, track: Track, steps: list[Fraction], offset: Fraction) -> Track:
        def snap_time(t: Fraction) -> tuple[Fraction, Fraction]:
            point, step = snap(t + offset, steps)
            return max(point - offset, Fraction(0)), step

        merged: dict[tuple, Any] = {}
        for event in track.events:
            start, step = snap_time(event.start)
            if isinstance(event, Hit):
                new = replace(event, start=start)
                key: tuple = ("hit", start, event.drum)
            else:
                end, _ = snap_time(event.start + event.duration)
                if end <= start:
                    end = start + step
                new = replace(event, start=start, duration=end - start)
                key = ("note", start, event.pitch) if isinstance(event, Note) else ("chord", start, event.symbol)
            old = merged.get(key)
            merged[key] = new if old is None else _merge(old, new)
        return replace(track, events=tuple(merged.values()), bars=None)


def _merge(a, b):
    """Two events that landed on the same slot: keep the longest and loudest."""
    if isinstance(a, (Note, Chord)) and b.duration > a.duration:
        a = replace(a, duration=b.duration)
    va, vb = getattr(a, "velocity", None), getattr(b, "velocity", None)
    if vb is not None and (va is None or vb > va):
        a = replace(a, velocity=vb)
    return a

"""dedupe_bars pass (FR-21): mark identical bars per track.

Writes `track.bars`, where entry i is the index of the first bar whose
content equals bar i. Events are left untouched, so emitters that do not
care can ignore the field. Bars are compared with core.time.slice_bars, the
same slicing the Strudel emitter renders from.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from ..core.ir import Song
from ..core.time import song_bars
from ..registry import Pass


class DedupeBars(Pass):
    """Detect identical bars per track so emitters can collapse repeats."""

    name = "dedupe_bars"

    def run(self, song: Song, options: Mapping[str, Any]) -> Song:
        tracks = []
        for track in song.tracks:
            first: dict[tuple, int] = {}
            bars = [first.setdefault(bar, i) for i, bar in enumerate(song_bars(song, track.events))]
            tracks.append(replace(track, bars=tuple(bars)))
        return replace(song, tracks=tuple(tracks))

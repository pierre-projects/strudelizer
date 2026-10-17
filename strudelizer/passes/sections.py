"""detect_sections pass (FR-22): name repeated multi-bar runs.

For songs without sections (MIDI files). The song is cut into equal blocks
of 16, 8, 4 or 2 bars (the longest that repeats, or `detect_sections:4`),
blocks with identical content in every track get the same name (part_a,
part_b, ... in order of first appearance), and the result becomes the
song's sections. Sections set by an importer are never replaced.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any, Mapping

from ..core.errors import StrudelizerError
from ..core.ir import Section, Song
from ..core.time import bar_offset, song_bars, song_length_bars
from ..registry import Pass

STAGE = "pass:detect_sections"
BLOCK_SIZES = (16, 8, 4, 2)


def _label(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("a") + rem) + letters
    return f"part_{letters}"


class DetectSections(Pass):
    """Name repeated multi-bar runs as sections (only for songs without sections)."""

    name = "detect_sections"
    default_option = "bars"

    def run(self, song: Song, options: Mapping[str, Any]) -> Song:
        if song.sections:
            return song  # never overwrite what an importer set
        sizes = BLOCK_SIZES
        if options.get("bars") is not None:
            try:
                size = int(options["bars"])
                assert size >= 1
            except (ValueError, AssertionError):
                raise StrudelizerError(
                    STAGE, f"block size must be a whole number of bars, not {options['bars']!r}",
                    location="option bars", fix="e.g. detect_sections:4",
                ) from None
            sizes = (size,)
        n_bars = song_length_bars(song)
        first = 1 if bar_offset(song.meta) else 0  # a pickup bar is its own section
        per_track = [song_bars(song, t.events) for t in song.tracks]
        signature = [tuple(bars[b] for bars in per_track) for b in range(n_bars)]

        for size in sizes:
            blocks = [range(s, min(s + size, n_bars)) for s in range(first, n_bars, size)]
            if len(blocks) < 2:
                continue
            keys = [tuple(signature[b] for b in block) for block in blocks]
            counts = Counter(keys)
            repeated = sum(1 for k in keys if counts[k] > 1)
            if repeated >= 2 and 2 * repeated >= len(blocks):
                break
        else:
            return song  # nothing repeats: leave the song without sections

        names: dict[tuple, str] = {}
        sections = [Section(0, 1, "pickup")] if first else []
        for block, key in zip(blocks, keys):
            name = names.setdefault(key, _label(len(names)))
            sections.append(Section(block.start, len(block), name))
        return replace(song, sections=tuple(sections))

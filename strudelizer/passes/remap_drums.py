"""remap_drums pass (FR-24): rename drum hits with a user mapping file.

    remap_drums:my_kit.yaml

The file maps IR drum names to IR drum names (YAML or JSON), and `null`
drops a drum:

    clap: snare
    ride: closed_hat
    cowbell: null

Hits that land on the same time and drum after renaming merge into one,
keeping the loudest.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..core.errors import StrudelizerError
from ..core.ir import DRUMS, Hit, Song
from ..registry import Pass

STAGE = "pass:remap_drums"


def load_mapping(source: Any) -> dict[str, str | None]:
    if isinstance(source, Mapping):
        data, where = dict(source), "option map"
    else:
        path = Path(str(source))
        where = str(path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise StrudelizerError(STAGE, f"cannot read mapping file: {exc.strerror}", location=where) from None
        except yaml.YAMLError as exc:
            raise StrudelizerError(STAGE, f"mapping file is not valid YAML/JSON: {exc}", location=where) from None
    if not isinstance(data, Mapping):
        raise StrudelizerError(STAGE, "the mapping must be a table of drum: drum", location=where,
                               fix="e.g. `clap: snare` on each line")
    vocab = ", ".join(DRUMS)
    for key, value in data.items():
        if key not in DRUMS:
            raise StrudelizerError(STAGE, f"unknown drum {key!r}", location=f"{where}: {key}", fix=f"use one of: {vocab}")
        if value is not None and value not in DRUMS:
            raise StrudelizerError(STAGE, f"unknown drum {value!r}", location=f"{where}: {key}",
                                   fix=f"use one of: {vocab}, or null to drop the drum")
    return dict(data)


class RemapDrums(Pass):
    """Rename or drop drum hits with a mapping file (remap_drums:kit.yaml)."""

    name = "remap_drums"
    default_option = "map"

    def run(self, song: Song, options: Mapping[str, Any]) -> Song:
        if options.get("map") is None:
            raise StrudelizerError(STAGE, "no mapping given", fix="e.g. remap_drums:my_kit.yaml")
        mapping = load_mapping(options["map"])
        tracks = []
        for track in song.tracks:
            if not any(isinstance(e, Hit) and e.drum in mapping for e in track.events):
                tracks.append(track)
                continue
            merged: dict[tuple, Hit] = {}
            others = []
            for e in track.events:
                if not isinstance(e, Hit):
                    others.append(e)
                    continue
                drum = mapping.get(e.drum, e.drum)
                if drum is None:
                    continue
                hit = replace(e, drum=drum)
                old = merged.get((hit.start, drum))
                if old is None or (hit.velocity or 0) > (old.velocity or 0):
                    merged[(hit.start, drum)] = hit
            tracks.append(replace(track, events=tuple(others) + tuple(merged.values()), bars=None))
        return replace(song, tracks=tuple(tracks))

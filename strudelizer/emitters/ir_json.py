"""IR JSON emitter (FR-33): write the Song IR so it can be inspected or edited."""

from __future__ import annotations

from typing import Any, Mapping

from ..core.ir import Song
from ..registry import Emitter


class IrJsonEmitter(Emitter):
    """The Song IR as JSON (.ir.json / .json), for inspection or hand edits."""

    name = "ir_json"
    extension = ".json"
    writes_ir = True

    def emit(self, song: Song, options: Mapping[str, Any]) -> str:
        return song.to_json()

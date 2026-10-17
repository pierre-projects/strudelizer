"""Request bodies. Responses are plain dicts, documented in README's UI section."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PassSpec(BaseModel):
    """One entry of the pass list, the JSON form of `quantize:grid=16`."""

    name: str
    options: dict[str, Any] = Field(default_factory=dict)


class ConvertRequest(BaseModel):
    ir: dict[str, Any]
    passes: list[PassSpec] = Field(default_factory=list)
    profile: str | None = None
    # Track ids to render; None means every track. Mute and solo regenerate the
    # code with this set rather than editing what the user is editing.
    tracks: list[str] | None = None


class ExportRequest(BaseModel):
    ir: dict[str, Any]
    format: str = "js"
    profile: str | None = None
    # The editor's text, sent when the user has changed the generated code so
    # the download is what they are hearing.
    code: str | None = None
    filename: str | None = None
    tracks: list[str] | None = None

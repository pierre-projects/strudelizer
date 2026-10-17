"""The four API endpoints, each a thin wrapper over `Pipeline`.

Endpoints are `async def` on purpose. They do CPU work rather than awaiting, so
they run one at a time on the event loop thread, which is what
`report.collect_warnings` needs: `warnings.catch_warnings` swaps a global filter
list and cannot be shared between threads. A conversion is well under a second
(NFR-6) and there is one user, so serialising them costs nothing.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Response, UploadFile

from strudelizer import registry
from strudelizer.core.errors import StrudelizerError
from strudelizer.core.ir import Song
from strudelizer.pipeline import Pipeline

from .plugins import catalog, default_emitter, instance
from .report import collect_warnings
from .schemas import ConvertRequest, ExportRequest

router = APIRouter()

STAGE = "ui"
MEDIA_TYPES = {".js": "text/javascript", ".json": "application/json", ".mid": "audio/midi"}
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@router.get("/plugins")
async def get_plugins() -> dict[str, Any]:
    """Installed importers, passes, emitters, profiles and styles."""
    return catalog()


@router.post("/import")
async def post_import(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    filename: str | None = Form(default=None),
    importer: str | None = Form(default=None),
    options: str = Form(default="{}"),
) -> dict[str, Any]:
    """An uploaded file or pasted text -> Song IR, warnings and the importer used."""
    importer_options = _clean(_json_object(options, "options"))
    if file is not None and file.filename:
        data = await file.read()
        name = _safe_name(file.filename)
    elif text is not None and text.strip():
        data = text.encode("utf-8")
        name = _safe_name(filename or "pasted.txt")
    else:
        raise StrudelizerError(
            STAGE,
            "nothing to import",
            fix="drop in a file, or paste a chord sheet into the text box",
        )

    with collect_warnings() as warnings_out:
        # A real file on disk, because importers read paths. Its basename is the
        # user's, so meta.source (and the generated header) match the CLI's
        # output for the same file, and nothing is left behind afterwards.
        with tempfile.TemporaryDirectory(prefix="strudelizer-ui-") as tmp:
            path = Path(tmp) / name
            path.write_bytes(data)
            try:
                plugin = registry.get_importer(importer) if importer else registry.find_importer(path)
                song = Pipeline(importer=plugin, passes=None, importer_options=importer_options).load(path)
            except StrudelizerError as exc:
                raise _hide_tempdir(exc, tmp) from None
    return {"ir": song.to_dict(), "importer": plugin.name, "warnings": warnings_out}


@router.post("/convert")
async def post_convert(request: ConvertRequest) -> dict[str, Any]:
    """Song IR + passes + profile -> Strudel code, the processed IR and warnings."""
    with collect_warnings() as warnings_out:
        song = Song.from_dict(request.ir, stage="import:ir")
        pipeline = Pipeline(
            passes=[(spec.name, _clean(spec.options)) for spec in request.passes],
            emitter="strudel",
            profile=_blank_to_none(request.profile),
        )
        song = pipeline.transform(song)
        # The returned IR is the whole song, so the song view still shows muted
        # tracks; only the code leaves them out.
        code = pipeline.emit(_only_tracks(song, request.tracks))
    return {"code": code, "ir": song.to_dict(), "warnings": warnings_out}


@router.post("/export")
async def post_export(request: ExportRequest) -> Response:
    """Song IR -> a file to download: .js, .mid or .ir.json."""
    emitter = _emitter_for_format(request.format)
    with collect_warnings() as warnings_out:
        song = _only_tracks(Song.from_dict(request.ir, stage="import:ir"), request.tracks)
        if request.code is not None and emitter.name == default_emitter():
            data: str | bytes = request.code  # the user's edits win over regenerating
        else:
            data = Pipeline(
                passes=None, emitter=emitter, profile=_blank_to_none(request.profile)
            ).emit(song)
    if isinstance(data, str):
        data = data.encode("utf-8")  # LF and UTF-8 on every OS, like the CLI (NFR-5)
    name = _download_name(request.filename, song, emitter)
    return Response(
        content=data,
        media_type=MEDIA_TYPES.get(emitter.extension, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Strudelizer-Warnings": json.dumps([w["text"] for w in warnings_out]),
        },
    )


# ---- helpers ----------------------------------------------------------------


def _json_object(text: str, field: str) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise StrudelizerError(
            STAGE, f"{field} is not valid JSON: {exc.msg}", location=field
        ) from None
    if not isinstance(value, dict):
        raise StrudelizerError(STAGE, f"{field} must be a JSON object", location=field)
    return value


def _clean(options: dict[str, Any]) -> dict[str, Any]:
    """Drop empty controls, so a cleared field means "use the default"."""
    return {k: v for k, v in options.items() if v is not None and v != ""}


def _blank_to_none(value: str | None) -> str | None:
    return value or None


def _hide_tempdir(exc: StrudelizerError, tmp: str) -> StrudelizerError:
    """Report `night_train.txt`, not the temporary directory it was copied into."""

    def strip(text: str | None) -> str | None:
        if not text:
            return text
        for prefix in (f"{tmp}\\", f"{tmp}/", tmp):
            text = text.replace(prefix, "")
        return text

    return StrudelizerError(exc.stage, strip(exc.message) or "", strip(exc.location), strip(exc.fix))


def _safe_name(filename: str) -> str:
    """The user's basename, with nothing that could escape the temp directory."""
    name = _UNSAFE.sub("_", Path(filename.replace("\\", "/")).name).strip("._") or "input"
    return name[:120]


def _only_tracks(song: Song, keep: list[str] | None) -> Song:
    if keep is None:
        return song
    tracks = tuple(t for t in song.tracks if t.id in keep)
    if not tracks:
        raise StrudelizerError(
            STAGE,
            "every track is muted, so there is nothing to play",
            fix="unmute a track, or solo one",
        )
    return replace(song, tracks=tracks)


def _emitter_for_format(fmt: str):
    """'js', 'mid', 'ir.json' -> the emitter whose extension matches, longest first."""
    wanted = "." + (fmt or "").lower().lstrip(".")
    best: tuple[int, Any] | None = None
    known = []
    for info in registry.available("emitter"):
        emitter = instance(info)
        extension = (getattr(emitter, "extension", "") or "").lower()
        if not extension:
            continue
        known.append(extension.lstrip("."))
        if wanted.endswith(extension) and (best is None or len(extension) > best[0]):
            best = (len(extension), emitter)
    if best is None:
        raise StrudelizerError(
            STAGE,
            f"no emitter writes {fmt!r} files",
            location="format",
            fix=f"use one of: {', '.join(sorted(set(known))) or 'none'}",
        )
    return best[1]


def _download_name(filename: str | None, song: Song, emitter: Any) -> str:
    """`<name>.js` and friends, whatever the name came in as: the UI passes the
    name of the file that was read, which carries the wrong extension."""
    if filename:
        stem = Path(_safe_name(filename)).stem.removesuffix(".ir")
    else:
        stem = song.meta.title or (Path(song.meta.source).stem if song.meta.source else None) or "song"
    stem = _UNSAFE.sub("_", stem).strip("._").lower() or "song"
    # `strudelize import` writes song.ir.json, so IR downloads match.
    suffix = ".ir.json" if getattr(emitter, "writes_ir", False) else emitter.extension
    return f"{stem}{suffix}"

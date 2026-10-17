"""Pipeline API (FR-43): importer -> passes -> emitter.

    from strudelizer import Pipeline
    code = Pipeline("midi", ["quantize:16", "dedupe_bars"], "strudel").run("song.mid")

The Song IR is validated against the JSON Schema (FR-5) wherever it enters
or leaves the process; `strict=True` also validates around every pass.
Plugins get this without doing anything themselves.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Union

from . import registry
from .core.errors import StrudelizerError
from .core.ir import Song
from .registry import Emitter, Importer, Pass

DEFAULT_PASSES = "quantize:16+8t,dedupe_bars"

PassSpec = Union[str, Pass, tuple]


def parse_pass_spec(spec: str | Iterable[PassSpec] | None) -> list[tuple[Pass, dict[str, Any]]]:
    """'quantize:16,dedupe_bars' -> [(Quantize(), {'grid': '16'}), (DedupeBars(), {})].

    A bare argument fills the pass's `default_option`; `key=value` sets any
    option, and several can follow the name separated by ':'.
    """
    if spec is None:
        return []
    items: Iterable[PassSpec] = (
        [s for s in spec.split(",") if s.strip()] if isinstance(spec, str) else spec
    )
    out = []
    for item in items:
        if isinstance(item, Pass):
            out.append((item, {}))
            continue
        if isinstance(item, tuple):
            name, options = item
            plugin = registry.get_pass(name) if isinstance(name, str) else name
            out.append((plugin, dict(options)))
            continue
        name, *args = _split_args(item.strip())
        plugin = registry.get_pass(name)
        options: dict[str, Any] = {}
        bare_seen = False
        for arg in args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                options[key.strip()] = value.strip()
            elif plugin.default_option:
                if bare_seen:
                    raise StrudelizerError(
                        f"pass:{name}",
                        f"the {name} pass takes one bare argument, got another: '{arg}'",
                        location=f"--passes {item}",
                        fix=f"write further options as {name}:key=value",
                    )
                bare_seen = True
                options[plugin.default_option] = arg
            else:
                raise StrudelizerError(
                    f"pass:{name}",
                    f"the {name} pass takes no bare argument '{arg}'",
                    location=f"--passes {item}",
                    fix=f"write options as {name}:key=value",
                )
        out.append((plugin, options))
    return out


def _split_args(text: str) -> list[str]:
    """Split 'name:arg:key=value' on ':', except a Windows drive colon:
    'remap_drums:C:\\kits\\a.yaml' -> ['remap_drums', 'C:\\kits\\a.yaml'].
    A drive colon follows a single letter that starts an argument (or its
    value, after '=') and comes before a slash or backslash."""
    parts: list[str] = []
    current = ""
    for i, char in enumerate(text):
        if char == ":":
            after = text[i + 1:i + 2]
            if after in ("\\", "/") and re.fullmatch(r"(?:[^=]*=)?\s*[A-Za-z]", current) and parts:
                current += char
                continue
            parts.append(current.strip())
            current = ""
            continue
        current += char
    parts.append(current.strip())
    return parts


def _stage(plugin: Any, kind: str) -> str:
    return f"{kind}:{getattr(plugin, 'name', '') or type(plugin).__name__}"


def strict_default() -> bool:
    """Strict mode is on when STRUDELIZER_STRICT is set to anything but 0."""
    return os.environ.get("STRUDELIZER_STRICT", "") not in ("", "0")


class Pipeline:
    """Run an importer, a list of passes, and an emitter.

    Each argument is a registered name or a plugin instance. `importer=None`
    picks one from the input file; `passes` is a spec string such as
    "quantize:16,dedupe_bars" or a list of names, instances or
    (name, options) tuples.

    The IR is validated against the schema at process boundaries: what an
    importer loads from a file, IR read with `read_ir`, and IR about to be
    written (`save_ir`, or an emitter with `writes_ir`). Passes running in
    this process are not re-validated unless `strict=True` (CLI `--strict`,
    or STRUDELIZER_STRICT=1), which checks every pass's input and output and
    the emitter's input.
    """

    def __init__(
        self,
        importer: str | Importer | None = None,
        passes: str | Sequence[PassSpec] | None = DEFAULT_PASSES,
        emitter: str | Emitter = "strudel",
        profile: str | Mapping[str, Any] | None = None,
        importer_options: Mapping[str, Any] | None = None,
        strict: bool | None = None,
    ) -> None:
        self.importer = registry.get_importer(importer) if isinstance(importer, str) else importer
        self.passes = parse_pass_spec(passes)
        self.emitter = registry.get_emitter(emitter) if isinstance(emitter, str) else emitter
        self.profile = registry.get_profile(profile) if isinstance(profile, str) else profile
        self.importer_options = dict(importer_options or {})
        self.strict = strict_default() if strict is None else strict
        # Songs are immutable, so one already validated (e.g. a pass's output,
        # which is the next stage's input) need not be checked again.
        self._valid: Song | None = None

    def validate(self, song: Any, stage: str, which: str) -> Song:
        """Schema-check a Song (once per object) and return it."""
        if song is not self._valid or not isinstance(song, Song):
            self._valid = _checked(song, stage, which)
        return song

    def load(self, path: str | Path) -> Song:
        importer = self.importer or registry.find_importer(path)
        stage = _stage(importer, "import")
        song = importer.load(path, self.importer_options)
        return self.validate(song, stage, "output")  # file load: a process boundary

    def transform(self, song: Song) -> Song:
        for plugin, options in self.passes:
            stage = _stage(plugin, "pass")
            if self.strict:
                self.validate(song, stage, "input")
                song = self.validate(plugin.run(song, options), stage, "output")
            else:
                song = _is_song(plugin.run(song, options), stage, "output")
        return song

    def emit(self, song: Song) -> str | bytes:
        stage = _stage(self.emitter, "emit")
        if self.strict or getattr(self.emitter, "writes_ir", False):
            self.validate(song, stage, "input")
        options: dict[str, Any] = {}
        if self.profile is not None:
            options["profile"] = self.profile
        return self.emitter.emit(song, options)

    def run(self, path: str | Path) -> str | bytes:
        return self.emit(self.transform(self.load(path)))

    def save_ir(self, song: Song, stage: str = "write:ir") -> str:
        """The IR as JSON text, validated because it leaves the process."""
        return self.validate(song, stage, "output").to_json()

    @staticmethod
    def read_ir(path: str | Path) -> Song:
        """Load a Song IR JSON file (validated)."""
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StrudelizerError("import:ir", f"cannot read file: {exc.strerror}", location=str(path)) from None
        return Song.from_json(text, stage="import:ir", location=str(path))


def _is_song(song: Any, stage: str, which: str) -> Song:
    if not isinstance(song, Song):
        raise StrudelizerError(
            stage,
            f"stage {which} is a {type(song).__name__}, not a Song",
            fix="plugins must return strudelizer.core.Song",
        )
    return song


def _checked(song: Any, stage: str, which: str) -> Song:
    _is_song(song, stage, which)
    try:
        return song.validate(stage)
    except StrudelizerError as exc:
        exc.message = f"{which} {exc.message[0].lower()}{exc.message[1:]}"
        raise

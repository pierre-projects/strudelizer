"""Plugin registry (NFR-2).

Importers, passes, emitters and sound profiles are discovered only through
Python entry points. Built-in plugins are declared in pyproject.toml exactly
as a third-party package would declare its own; nothing here imports a
plugin by name.

    [project.entry-points."strudelizer.importers"]
    mytab = "my_package.tab:TabImporter"
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any, Mapping

from .core.errors import StrudelizerError
from .core.ir import Song

GROUPS = {
    "importer": "strudelizer.importers",
    "pass": "strudelizer.passes",
    "emitter": "strudelizer.emitters",
    "profile": "strudelizer.profiles",
    "style": "strudelizer.styles",
}

Options = Mapping[str, Any]


# ---- plugin interfaces ------------------------------------------------------


class Importer:
    """Reads one input format into a Song. Subclass and set `name`/`extensions`."""

    name: str = ""
    extensions: tuple[str, ...] = ()

    def can_handle(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def load(self, path: str | Path, options: Options) -> Song:
        raise NotImplementedError


class Pass:
    """A pure Song -> Song transform.

    `default_option` names the option a bare CLI argument fills, so
    `quantize:16` means `{"grid": "16"}`.
    """

    name: str = ""
    default_option: str | None = None

    def run(self, song: Song, options: Options) -> Song:
        raise NotImplementedError


class Emitter:
    """Writes a Song. `extension` picks it from `-o` file names.

    `emit` returns text, or bytes when `binary` is True. Set `writes_ir`
    when the output is the IR itself, so the pipeline validates it first.
    """

    name: str = ""
    extension: str = ""
    binary: bool = False
    writes_ir: bool = False

    def emit(self, song: Song, options: Options) -> str | bytes:
        raise NotImplementedError


# ---- discovery ----------------------------------------------------------------


@dataclass(frozen=True)
class PluginInfo:
    kind: str
    name: str
    target: str
    distribution: str
    entry_point: EntryPoint

    def load(self) -> Any:
        try:
            return self.entry_point.load()
        except Exception as exc:  # a broken plugin must not hide the others
            raise StrudelizerError(
                "registry",
                f"could not load {self.kind} plugin '{self.name}' ({self.target}): {exc}",
                location=f"distribution {self.distribution}",
                fix=f"reinstall or uninstall the '{self.distribution}' package",
            ) from exc


def _discover(group: str) -> list[EntryPoint]:
    return list(entry_points(group=group))


def available(kind: str) -> list[PluginInfo]:
    """All installed plugins of one kind, sorted by name."""
    found: dict[str, PluginInfo] = {}
    for ep in _discover(GROUPS[kind]):
        dist = ep.dist.name if getattr(ep, "dist", None) is not None else "unknown"
        info = PluginInfo(kind, ep.name, ep.value, dist, ep)
        previous = found.get(ep.name)
        if previous is not None and previous.target != info.target:
            raise StrudelizerError(
                "registry",
                f"two {kind} plugins are named '{ep.name}': "
                f"{previous.target} ({previous.distribution}) and {info.target} ({info.distribution})",
                fix="uninstall one of the two packages",
            )
        found[ep.name] = info
    return [found[name] for name in sorted(found)]


def _instance(kind: str, name: str) -> Any:
    for info in available(kind):
        if info.name == name:
            obj = info.load()
            return obj() if isinstance(obj, type) else obj
    names = ", ".join(i.name for i in available(kind)) or "none"
    raise StrudelizerError(
        "registry",
        f"no {kind} named '{name}'",
        fix=f"installed {kind}s: {names} (see `strudelize list`)",
    )


def get_importer(name: str) -> Importer:
    return _instance("importer", name)


def get_pass(name: str) -> Pass:
    return _instance("pass", name)


def get_emitter(name: str) -> Emitter:
    return _instance("emitter", name)


def find_importer(path: str | Path) -> Importer:
    """The first importer (by name) whose can_handle accepts the path."""
    for info in available("importer"):
        obj = info.load()
        importer = obj() if isinstance(obj, type) else obj
        if importer.can_handle(path):
            return importer
    known = []
    for info in available("importer"):
        obj = info.load()
        exts = ", ".join(getattr(obj, "extensions", ()) or ())
        known.append(f"{info.name} ({exts})" if exts else info.name)
    raise StrudelizerError(
        "import",
        "no installed importer can read this file",
        location=str(path),
        fix=f"installed importers: {'; '.join(known) or 'none'}; pass --importer to force one",
    )


def emitter_for_output(path: str | Path | None) -> Emitter:
    """Pick an emitter from the output file name; Strudel when unknown."""
    if path is not None:
        name = Path(path).name.lower()
        best: tuple[int, Emitter] | None = None
        for info in available("emitter"):
            obj = info.load()
            emitter = obj() if isinstance(obj, type) else obj
            ext = getattr(emitter, "extension", "")
            if ext and name.endswith(ext) and (best is None or len(ext) > best[0]):
                best = (len(ext), emitter)
        if best is not None:
            return best[1]
    return get_emitter("strudel")


def get_style(name_or_path: str) -> dict[str, Any]:
    """An arrange style by registered name, or from a .yaml file path."""
    from .styles import load_style_file, validate_style

    path = Path(name_or_path)
    if path.suffix.lower() in (".yaml", ".yml") or path.exists():
        return load_style_file(path)
    for info in available("style"):
        if info.name == name_or_path:
            loader = info.load()
            data = loader() if callable(loader) else loader
            return validate_style(data, location=f"style '{info.name}' ({info.distribution})")
    names = ", ".join(i.name for i in available("style")) or "none"
    raise StrudelizerError(
        "registry",
        f"no style named '{name_or_path}'",
        fix=f"installed styles: {names}; or pass a path to a .yaml style",
    )


def get_profile(name_or_path: str) -> dict[str, Any]:
    """A sound profile by registered name, or from a .yaml file path."""
    from .profiles import load_profile_file, validate_profile

    path = Path(name_or_path)
    if path.suffix.lower() in (".yaml", ".yml") or path.exists():
        return load_profile_file(path)
    for info in available("profile"):
        if info.name == name_or_path:
            loader = info.load()
            data = loader() if callable(loader) else loader
            return validate_profile(data, location=f"profile '{info.name}' ({info.distribution})")
    names = ", ".join(i.name for i in available("profile")) or "none"
    raise StrudelizerError(
        "registry",
        f"no profile named '{name_or_path}'",
        fix=f"installed profiles: {names}; or pass a path to a .yaml profile",
    )

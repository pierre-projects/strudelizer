"""The registry as JSON for `GET /api/plugins`.

Everything the options panel draws comes from here, so installing a plugin is
all it takes to make it appear: there is no list of plugin names in the
frontend. A plugin that fails to load is reported rather than hidden, the way
`strudelize list` reports it.
"""

from __future__ import annotations

from typing import Any

from strudelizer import __version__, registry
from strudelizer.core.errors import StrudelizerError
from strudelizer.pipeline import DEFAULT_PASSES, parse_pass_spec

from .options import describe, plugin_label


def summary(obj: Any) -> str:
    """The first line of a plugin's docstring, as `strudelize list` shows it."""
    doc = (getattr(obj, "__doc__", None) or "").strip()
    return doc.splitlines()[0] if doc else ""


def instance(info: registry.PluginInfo) -> Any:
    obj = info.load()
    return obj() if isinstance(obj, type) else obj


def _common(info: registry.PluginInfo, plugin: Any, broken: str | None) -> dict[str, Any]:
    options = None if broken else describe(info.kind, info.name, plugin)
    return {
        "name": info.name,
        "label": plugin_label(info.kind, info.name, plugin),
        "summary": broken or summary(plugin),
        "distribution": info.distribution,
        "options": options,
        # Nobody describes this plugin's options: the panel offers key=value.
        "custom": options is None and not broken,
        "broken": bool(broken),
    }


def _load(info: registry.PluginInfo) -> tuple[Any, str | None]:
    try:
        return instance(info), None
    except StrudelizerError as exc:
        return None, f"BROKEN: {exc.message}"


def _plugins(kind: str) -> list[tuple[registry.PluginInfo, Any, str | None]]:
    out = []
    for info in registry.available(kind):
        plugin, broken = _load(info)
        out.append((info, plugin, broken))
    return out


def catalog() -> dict[str, Any]:
    """Every installed plugin, with the options schema the frontend draws from."""
    importers = []
    accept: list[str] = []
    for info, plugin, broken in _plugins("importer"):
        extensions = list(getattr(plugin, "extensions", ()) or ())
        accept.extend(ext for ext in extensions if ext not in accept)
        importers.append({**_common(info, plugin, broken), "extensions": extensions})

    passes = []
    for info, plugin, broken in _plugins("pass"):
        passes.append(
            {**_common(info, plugin, broken), "default_option": getattr(plugin, "default_option", None)}
        )

    emitters = []
    for info, plugin, broken in _plugins("emitter"):
        extension = getattr(plugin, "extension", "") or ""
        emitters.append(
            {
                **_common(info, plugin, broken),
                "extension": extension,
                "format": extension.lstrip("."),
                "binary": bool(getattr(plugin, "binary", False)),
                "writes_ir": bool(getattr(plugin, "writes_ir", False)),
            }
        )

    return {
        "version": __version__,
        "importers": importers,
        "passes": passes,
        "emitters": emitters,
        "profiles": [_common(i, p, b) for i, p, b in _plugins("profile")],
        "styles": [_common(i, p, b) for i, p, b in _plugins("style")],
        "default_passes": default_passes(),
        "accept": accept,
        "uninstalled": uninstalled(),
    }


def uninstalled() -> list[dict[str, Any]]:
    """Plugins behind an optional extra that is not installed.

    The UI shows these greyed out with their install command, so a `.gp5` that
    cannot be read says what to install instead of "no importer can read this".
    """
    # `unavailable` arrived with the plugins that sit behind an extra; a core
    # without it has none to report.
    unavailable = getattr(registry, "unavailable", None)
    if unavailable is None:
        return []
    out = []
    for kind in registry.GROUPS:
        for info in unavailable(kind):
            try:
                extensions = list(getattr(instance(info), "extensions", ()) or ())
            except StrudelizerError:
                extensions = []
            out.append(
                {
                    "kind": kind,
                    "name": info.name,
                    "extensions": extensions,
                    "install": info.install_hint,
                    "missing": info.missing_modules(),
                }
            )
    return out


def default_passes() -> list[dict[str, Any]]:
    """The CLI's default pass list, so the UI starts where `strudelize` does."""
    return [
        {"name": plugin.name, "options": dict(options)}
        for plugin, options in parse_pass_spec(DEFAULT_PASSES)
    ]

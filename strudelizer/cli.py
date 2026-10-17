"""Command line interface (FR-40 to FR-42).

    strudelize song.mid -o song.js [--profile lofi] [--passes quantize:16,dedupe_bars]
    strudelize chords.txt --bpm 90 --style lofi -o song.js
    strudelize import song.mid -o song.ir.json
    strudelize pass song.ir.json --passes quantize:16 -o song.q.ir.json
    strudelize emit song.ir.json -o song.js [--profile techno]
    strudelize list
    strudelize ui
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Any, Sequence

from . import __version__, registry
from .core.errors import StrudelizerError, StrudelizerWarning
from .pipeline import DEFAULT_PASSES, Pipeline

COMMANDS = ("import", "pass", "emit", "list", "ui")


def _write(data: str | bytes, output: str | None) -> None:
    if isinstance(data, str):
        data = data.encode("utf-8")  # always LF, never platform newlines (NFR-5)
    if output is None or output == "-":
        sys.stdout.buffer.write(data)
        sys.stdout.flush()
        return
    try:
        Path(output).write_bytes(data)
    except OSError as exc:
        raise StrudelizerError("write", f"cannot write output: {exc.strerror}", location=output) from None


def _add_import_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--importer", help="force an importer by name")
    p.add_argument("--bpm", type=float, help="tempo for inputs without one, e.g. chord sheets (default 100)")
    p.add_argument("--beats-per-chord", help="chord sheets: beats each chord lasts (default: one bar)")
    p.add_argument("--pickup", help="beats in a partial first bar (overrides what the importer detects)")


def _add_strict(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strict", action="store_true", help="validate the IR after every pass, not only at file boundaries")


def _one_shot_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="strudelize",
        description="Convert a music file into a Strudel pattern.",
        epilog=f"Staged commands: strudelize {{{','.join(COMMANDS)}}} --help",
    )
    p.add_argument("input", help="input file, e.g. song.mid or chords.txt")
    p.add_argument("-o", "--output", help="output file (.js Strudel, .mid MIDI, .json IR); stdout if omitted")
    p.add_argument("--profile", help="sound profile name or .yaml path (default: default)")
    p.add_argument("--passes", default=DEFAULT_PASSES, help=f'comma-separated passes (default: "{DEFAULT_PASSES}"; "" for none)')
    p.add_argument("--style", help="arrange missing drums and bass with a style (lofi, rock, four_on_floor, or a .yaml path)")
    _add_import_options(p)
    p.add_argument("--emitter", help="force an emitter by name (default: from the output extension)")
    _add_strict(p)
    p.add_argument("--version", action="version", version=f"strudelize {__version__}")
    return p


def _staged_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="strudelize", description="Run one pipeline stage.")
    sub = p.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="input file -> Song IR JSON")
    imp.add_argument("input")
    imp.add_argument("-o", "--output", help="output .ir.json (stdout if omitted)")
    _add_import_options(imp)

    pas = sub.add_parser("pass", help="Song IR JSON -> passes -> Song IR JSON")
    pas.add_argument("input", help="input .ir.json")
    pas.add_argument("--passes", required=True, help="comma-separated passes, e.g. quantize:16,dedupe_bars")
    pas.add_argument("-o", "--output", help="output .ir.json (stdout if omitted)")
    _add_strict(pas)

    emit = sub.add_parser("emit", help="Song IR JSON -> output format")
    emit.add_argument("input", help="input .ir.json")
    emit.add_argument("-o", "--output", help="output file (stdout if omitted)")
    emit.add_argument("--emitter", help="emitter name (default: from the output extension, else strudel)")
    emit.add_argument("--profile", help="sound profile name or .yaml path")

    sub.add_parser("list", help="show installed importers, passes, emitters, profiles and styles")

    ui = sub.add_parser("ui", help="open the local web UI in a browser (needs the [ui] extra)")
    ui.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    ui.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    ui.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    return p


def _ui(args: argparse.Namespace) -> None:
    """The only thing the core knows about the UI: how to start it."""
    try:
        from strudelizer_ui.server import serve
    except ImportError as exc:
        raise StrudelizerError(
            "ui",
            f"the web UI is not installed ({exc.name})",
            fix='install it with: pip install -e ".[ui]"',
        ) from None
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


def _emitter(name: str | None, output: str | None):
    return registry.get_emitter(name) if name else registry.emitter_for_output(output)


def _importer_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if args.bpm is not None:
        options["bpm"] = args.bpm
    if args.beats_per_chord is not None:
        options["beats_per_chord"] = args.beats_per_chord
    if args.pickup is not None:
        options["pickup"] = args.pickup
    return options


def _with_style(passes: str, style: str | None) -> str:
    """--style lofi puts `arrange:style=lofi` before the other passes."""
    if not style:
        return passes
    names = [p.split(":", 1)[0].strip() for p in passes.split(",") if p.strip()]
    if "arrange" in names:
        raise StrudelizerError(
            "cli", "--style and an arrange pass in --passes both choose a style", fix="use one of them"
        )
    return ",".join([f"arrange:style={style}"] + ([passes] if passes.strip() else []))


def _summary(obj) -> str:
    doc = (getattr(obj, "__doc__", None) or "").strip()
    return doc.splitlines()[0] if doc else ""


def _list() -> str:
    lines = []
    for kind in registry.GROUPS:
        title = {"pass": "passes"}.get(kind, f"{kind}s")
        lines.append(f"{title}:")
        plugins = registry.available(kind)
        if not plugins:
            lines.append("  (none)")
        width = max((len(p.name) for p in plugins), default=0)
        for info in plugins:
            try:
                summary = _summary(info.load())
            except StrudelizerError as exc:
                summary = f"BROKEN: {exc.message}"
            lines.append(f"  {info.name.ljust(width)}  {summary}  [{info.distribution}]")
    return "\n".join(lines) + "\n"


def run(argv: Sequence[str]) -> None:
    argv = list(argv)
    if argv and argv[0] in COMMANDS:
        args = _staged_parser().parse_args(argv)
        if args.command == "list":
            _write(_list(), None)
        elif args.command == "ui":
            _ui(args)
        elif args.command == "import":
            pipeline = Pipeline(importer=args.importer, passes=None, importer_options=_importer_options(args))
            _write(pipeline.save_ir(pipeline.load(args.input)), args.output)
        elif args.command == "pass":
            pipeline = Pipeline(passes=args.passes, strict=args.strict or None)
            song = pipeline.transform(Pipeline.read_ir(args.input))
            _write(pipeline.save_ir(song), args.output)
        else:
            pipeline = Pipeline(passes=None, emitter=_emitter(args.emitter, args.output), profile=args.profile)
            _write(pipeline.emit(Pipeline.read_ir(args.input)), args.output)
        return
    args = _one_shot_parser().parse_args(argv)
    pipeline = Pipeline(
        importer=args.importer,
        passes=_with_style(args.passes, args.style),
        emitter=_emitter(args.emitter, args.output),
        profile=args.profile,
        importer_options=_importer_options(args),
        strict=args.strict or None,
    )
    _write(pipeline.run(args.input), args.output)


def main(argv: Sequence[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Messages may quote chord symbols such as CΔ or Bø; never crash on a
    # console whose encoding cannot show them (e.g. cp1252 on Windows).
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            pass
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", StrudelizerWarning)
        try:
            run(argv)
            code = 0
        except StrudelizerError as exc:
            code = 1
            error = exc
        finally:
            for w in caught:
                if isinstance(w.message, StrudelizerWarning):
                    print(f"warning [{w.message.stage}]: {w.message.message}", file=sys.stderr)
                else:
                    print(warnings.formatwarning(w.message, w.category, w.filename, w.lineno), end="", file=sys.stderr)
    if code:
        where = f" at {error.location}" if error.location else ""
        print(f"error [{error.stage}]{where}: {error.message}", file=sys.stderr)
        if error.fix:
            print(f"  fix: {error.fix}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())

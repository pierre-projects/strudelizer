# Strudelizer web UI plan

A local, offline web app around the existing Python API: drop in a song, hear
the Strudel result in the page, tweak, download. Nothing under `strudelizer/`
changes except one documented CLI exception (below).

## Shape

```
strudelizer_ui/            [ui] extra: fastapi, uvicorn, python-multipart
  server.py                uvicorn + open the browser; `strudelize ui`
  app.py                   FastAPI app, mounts static/
  routes.py                /api/plugins /api/import /api/convert /api/export
  schemas.py               request/response models
  plugins.py               registry -> JSON (summaries from docstrings)
  options.py               option metadata table (see below)
  report.py               StrudelizerError/Warning -> JSON in the CLI's wording
  static/                  built frontend (committed, so pip install is enough)
  frontend/                Vite + TypeScript + Preact source
```

| Endpoint | In | Out |
| --- | --- | --- |
| `GET /api/plugins` | | importers, passes, emitters, profiles, styles; each with an options schema, plus `default_passes` |
| `POST /api/import` | upload or pasted text, importer override, importer options | `{ir, importer, warnings}` |
| `POST /api/convert` | `{ir, passes[], profile, tracks?}` | `{code, ir, warnings}` |
| `POST /api/export` | `{ir, format: js\|mid\|ir.json, profile, code?}` | the file |

Errors are HTTP 400 with `{"error": {stage, message, location, fix, text}}`,
where `text` is the CLI's exact string (`error [stage] at <loc>: msg` + `fix:`).
Warnings carry `{stage, message, line?}`; the line comes from the `line N:`
prefix the chord-sheet importer already writes.

Each endpoint runs the public API only: `Pipeline(passes=[(name, options)],
emitter=..., profile=...)`, `Song.from_dict` / `to_dict`, `registry.available`.
Uploads are written to a `TemporaryDirectory` under their original basename so
`meta.source` (and therefore the output) is unchanged, then deleted. Endpoints
are `async def` so conversions serialise in one thread: `warnings.catch_warnings`
is process-global and cannot be shared between threads.

## Option metadata

The registry carries no option metadata (plugins just read `options.get(...)`),
so `strudelizer_ui/options.py` holds a table keyed by kind and plugin name:
`{name, label, type, default, help, choices | choices_from}`. A plugin that
declares its own `options` attribute wins, and a plugin in neither case gets a
generic `key=value` editor, so a newly installed plugin still works. Labels are
musician-facing ("Drum style"); `help` carries the technical name
(`arrange:style=lofi`).

## Playback

`@strudel/repl@1.2.6` (the official `<strudel-editor>` web component; matches
the repo's pinned `@strudel/*@1.2.6`). Its `dist/` is vendored into
`frontend/public/strudel/` and loaded with a script tag, because the bundle
resolves `assets/clockworker-*.js` relative to `document.currentScript`. No CDN,
so everything but Strudel's sample loading works offline.

- `el.editor` is a `StrudelMirror`: `setCode`, `evaluate`, `start`, `stop`.
  Re-converting calls `setCode` then `evaluate` only if it is already playing,
  so playback keeps running.
- `el.editor.editor` is the CodeMirror view, so clicking a bar can select and
  scroll to the matching line with `dispatch({selection, scrollIntoView: true})`.
- "Open in strudel.cc" uses the verified share format:
  `https://strudel.cc/#` + `encodeURIComponent(base64(utf8(code)))`
  (`code2hash` in `@strudel/core`).

## Screens

1. **Input** - drop zone (accepted extensions from `/api/plugins`), file picker,
   paste area, auto-detected importer with an override dropdown.
2. **Options** - built from `/api/plugins`: tempo, sound profile, style,
   quantize grid, transpose, pickup, and the ordered, toggleable pass list.
   Importer options only when that importer is active. Changing an option
   re-imports (importer options) or re-converts (everything else), debounced.
3. **Song view** - bar ruler with section blocks, chord symbol per bar, and a
   piano roll / drum grid per track, grouped by role. Clicking a bar highlights
   the `const <section>` or `// <track> (<role>)` line it maps to.
4. **Code + playback** - the embedded editor, play/stop, "Reset to generated",
   and per-track mute/solo, which re-converts with a `tracks` filter rather than
   editing the user's code.
5. **Problems** - warnings and unparsed lines; clicking one shows the pasted
   source line or the bar.
6. **Export** - `.js`, `.mid`, `.ir.json`; `.js` sends the edited buffer when
   the user has changed it.

Dark theme by default with a light toggle, `ctrl+enter` play (as in Strudel),
`ctrl+.` stop, `alt+r` re-convert. Labelled controls, visible focus, 1280px down
to tablet width.

## The one core change

`strudelize ui` needs a subcommand, and `strudelizer/cli.py` hardcodes
`COMMANDS`. The exception is ~12 lines: `"ui"` in `COMMANDS`, a subparser with
`--host/--port/--no-browser`, and a lazy import that raises the usual
`StrudelizerError` with `fix: pip install -e ".[ui]"` when the extra is missing.
No other file under `strudelizer/` is touched.

## Tests

- `tests/test_ui_api.py`: every endpoint against the existing fixtures
  (`multitrack_repeats.mid`, `night_train.txt`, `sections_chords.ir.json`), plus
  errors: unknown importer, unreadable file, bad pass option, invalid IR,
  unknown export format. Skipped when the extra is not installed.
- `frontend/tests/ui.spec.ts` (Playwright): load a MIDI fixture and a pasted
  chord sheet, change the style, assert the code updates, export all three
  formats, and smoke-test playback with no console errors.
- `scripts/check.py ui` runs the frontend build and the Playwright suite;
  `python scripts/check.py` stays green.

## Order

API + tests -> page that imports and shows code -> embedded playback -> options
panel -> song view -> problems -> export -> polish. A commit after each step.

# Strudelizer P3 plan (tabs and notation)

Housekeeping first: git (`.gitattributes` keeps goldens LF), dev tools in the
`dev` extra, `scripts/check.py` (lint + strict tests + Strudel check, without
make), and `{x_pickup}` as the canonical ChordPro directive.

| Module | PRD | Notes |
| --- | --- | --- |
| `core/tab.py` | FR-13 | Staff blocks, tuning from labels / names, capo, even8/even16/columns rhythm |
| `importers/ascii_tab.py` | FR-13 | `.tab` and tab-dominated `.txt`; header lines; unparsed-line report |
| `importers/chordsheet.py` | FR-13 hook | Imports `{start_of_tab}` and bare tab blocks; `{capo}` |
| `importers/guitarpro.py` | FR-12 | `[guitarpro]` extra; unfold repeats/endings; ties, dead and grace notes |
| `importers/musicxml.py` | FR-14 | `[musicxml]` extra; expandRepeats, stripTies, harmony symbols, pickup |
| `registry.py` | NFR-4 | Plugins behind an extra are registered only when it is installed |
| `core/gm.py` | | GM tables and role heuristic shared by importers |
| `emitters/strudel.py` | (investigate) | Hold tied notes: `[...]@k` multi-cycle steps |

Tests: fixtures in code (`make_gp_fixtures.py`, `make_mxl.py`) or by hand; goldens;
Strudel validity on every output; tab/GP/MusicXML → IR → MIDI → IR with every
pitch matching.

---

# Strudelizer P2 plan (chord sheets)

P1 follow-ups first: validate at process boundaries only (`--strict` for every
pass, tests always strict), drums cowbell/tambourine/shaker, `meta.pickup_beats`
(IR v2, v1 migrated on load), README limitations.

| Module | PRD | Notes |
| --- | --- | --- |
| `core/theory.py` | FR-11, Decision 2 | Strict chord grammar → root/quality/extensions/bass, voicings, keys |
| `importers/chordsheet.py` | FR-11 | ChordPro, chords-over-lyrics, bar lines; sections; unparsed-line report |
| `styles/*.yaml` + `strudelizer.styles` group | FR-23 | lofi, rock, four_on_floor: drum patterns, bass rule, chord rhythm |
| `passes/arrange.py` | FR-23 | Missing drums/bass; slash note in bass, chord voiced without it |
| `passes/sections.py` | FR-22 | detect_sections for MIDI; never overwrites |
| `passes/transpose.py`, `passes/remap_drums.py` | FR-24 | |
| `emitters/midi.py` | FR-32 | Round trip upgraded to MIDI → IR → MIDI → IR |

Tests: three hand-written sheets (one per format, each with every Decision 2
spelling, sections, a slash chord, a pickup and an unparsed line). Goldens are
with no style and each style, and every output goes through the Strudel check.

---

# Strudelizer P1 plan

Scope: PRD phase P1 only (MIDI → Song IR → Strudel). Nothing tagged P2 to P5.

## Modules

| Module | PRD | Notes |
| --- | --- | --- |
| `core/ir.py`, `core/schema.json` | FR-1 to FR-6 | Dataclasses; times are `Fraction` (JSON `"n/d"`); JSON Schema 2020-12 |
| `core/time.py` | | Fraction format, bar math, `slice_bars()` shared by dedupe + emitter |
| `core/theory.py` | | MIDI pitch ↔ note name (`c4` = 60) |
| `core/errors.py` | FR-44 | `StrudelizerError(stage, message, location, fix)`, `StrudelizerWarning` |
| `registry.py` | NFR-2 | Entry-point groups `strudelizer.{importers,passes,emitters,profiles}` |
| `importers/midi.py` | FR-10 | mido; GM channel 10 → IR drum vocabulary; dominant tempo + warning |
| `passes/quantize.py` | FR-20 | Grids `8`, `16`, `32`, `8t`, `16t`, combined with `+` |
| `passes/dedupe_bars.py` | FR-21 | Writes `track.bars` (bar → first identical bar) |
| `emitters/strudel.py` | FR-30 | All Strudel syntax lives here |
| `emitters/ir_json.py` | FR-33 | |
| `profiles/*.yaml` | FR-31 | default, lofi, techno |
| `pipeline.py`, `cli.py` | FR-40 to FR-44 | Schema validation at every stage boundary |

## IR conventions (confirmed)
- A beat is the time-signature denominator unit; `meta.bpm` counts those beats.
- dedupe_bars writes the optional per-track `bars: [int]`.
- `hit` has an optional `velocity`.

## Order
IR + schema → registry → MIDI importer (+ fixture generator) → quantize →
Strudel emitter (+ Node validator) → dedupe_bars → profiles → pipeline/CLI →
golden / round-trip / determinism / validity suites → README.
Tests run green after every step.

## Tests
- `tests/fixtures/make_fixtures.py` builds 5 MIDI files with mido.
- Golden: `<name>.ir.json` (import output) and `<name>.js` (one-shot default
  pipeline); `STRUDELIZER_UPDATE_GOLDEN=1` regenerates.
- Round-trip: independent mido reader vs IR after quantize, ≥ 98% match.
- Determinism: in-process and cross-process (different `PYTHONHASHSEED`).
- Strudel validity: `tests/strudel/validate.mjs` on pinned `@strudel/*@1.2.6`,
  evaluates each `.js`, queries cycles 0 to 4, and the events are compared with the IR.

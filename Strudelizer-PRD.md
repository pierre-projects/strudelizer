# Strudelizer PRD

Oct 16, 2026

## Overview

Strudelizer converts existing music (MIDI files, chord sheets, guitar tabs, and later raw audio) into playable, readable [Strudel](https://strudel.cc) live-coding patterns. It is built like a compiler: importers translate each input format into one shared song format (the Song IR), cleanup passes transform the IR, and emitters write Strudel code.

Today, getting a song into Strudel means transcribing it by hand, bar by bar. Strudelizer automates the tedious part so musicians can start live-coding from a song they already know, then remix it by editing code.

## Goals and non-goals

**Goals**

1. Convert symbolic inputs (MIDI, chord sheets, guitar tabs, MusicXML) into Strudel code that plays correctly on strudel.cc with no edits.
2. Produce code a human wants to edit: short, repeated bars collapsed, sections named, sounds chosen from a readable profile.
3. Keep the system modular: a new input or output format is one new plugin, with no change to the core.
4. Keep it portable: the core runs anywhere Python 3.10+ runs, with no heavy dependencies, and every stage can be run on its own through the JSON IR.
5. Add audio input last, as a separate optional package.

**Non-goals**

- Reproducing the original recording's sound or timbre. Strudelizer captures notes, chords, and rhythm.
- Perfect transcription of dense or polyphonic audio.
- A graphical editor or DAW. Strudel itself is the editor.
- Hosting or distributing copyrighted songs. Users bring their own inputs.

## Users and use cases

| User | Input they have | What they want |
| --- | --- | --- |
| Live coder | A MIDI file of a song | A Strudel version to perform and remix live |
| Guitarist learning Strudel | A chord sheet or tab from a song they play | A backing groove under the chords to jam over |
| Producer | A Guitar Pro or MusicXML file | Parts split into tracks, ready to rework in code |
| Educator | Simple songs in any format | Readable examples that show how songs map to patterns |
| Developer | Any format | A library and IR to build their own tools on |

## Scope by release

P1 ships the smallest end-to-end slice (MIDI in, Strudel out) to prove the IR. Each later phase adds input types behind the same IR, and audio, the hardest and heaviest, ships last.

```
P1  Core slice: MIDI to Strudel
    Song IR + schema, plugin registry, MIDI importer, quantize, dedupe_bars,
    Strudel emitter, profiles, CLI
    Gate: every MIDI fixture plays on strudel.cc in CI with no edits
        |
        v
P2  Chord sheets
    Chord sheet importer, detect_sections, arrange with style templates,
    transpose, MIDI emitter
    Gate: a chord sheet becomes a playable groove with chords, bass and drums
        |
        v
P3  Tabs and notation
    Guitar Pro importer, ASCII tab importer with rhythm hints, MusicXML importer
    Gate: tab fixtures round-trip through MIDI with correct pitches
        |
        v
P4  Packaging and plugin ecosystem
    PyPI release with optional extras, plugin author guide, more sound
    profiles, core Docker image
    Gate: a third-party plugin installs and runs with no core changes
        |
        v
P5  Audio input (separate package)
    Demucs stems, beat tracking, Basic Pitch, drum transcription,
    simplify and detect_tempo passes
    Gate: drums and bass of test songs are recognisable after cleanup
```

A phase starts only when the previous gate passes, so every release is usable on its own.

## Functional requirements

Requirements are tagged by the phase that delivers them (P1 to P5, see Scope by release).

### Song IR (P1)

- **FR-1** The IR is a versioned JSON document with `meta` (title, bpm, time signature, key), `sections` (name, start bar, length), and `tracks`.
- **FR-2** Each track has an `id`, a `role` (drums, bass, chords, melody, vocal, other), an optional instrument hint, and a list of events.
- **FR-3** Event types are `note` (start, duration, MIDI pitch, velocity), `hit` (start, drum name from a fixed vocabulary), and `chord` (start, duration, chord symbol, optional pitches).
- **FR-4** All times are in beats, stored as exact fractions (for example `"1/3"`) so triplets and swing survive round trips.
- **FR-5** A published JSON Schema validates every IR file. Every stage validates its input and output against it.
- **FR-6** All fields except events are optional. Missing tempo, key, or sections are filled by passes or defaults.

### Importers

Each importer implements `can_handle(path) -> bool` and `load(path, options) -> Song`.

| ID | Importer | Phase | Library | Notes |
| --- | --- | --- | --- | --- |
| FR-10 | MIDI (.mid) | P1 | mido / pretty_midi | Reads tempo, time signature, tracks; maps GM channel 10 to drum hits |
| FR-11 | Chord sheet (ChordPro, chords-over-lyrics, plain bar lines like `\| Am \| F \| C G \|`) | P2 | Custom parser | Detects section labels ([Verse], [Chorus]); needs `--bpm` and beats-per-chord defaults |
| FR-12 | Guitar Pro (.gp3 to .gp5) | P3 | PyGuitarPro | Full rhythm, tuning, multiple tracks |
| FR-13 | ASCII tab | P3 | Custom parser | Converts string + fret + tuning to pitch; rhythm from a user hint (default even 8ths) |
| FR-14 | MusicXML | P3 | music21 (optional extra) | Notes, chords, and harmony symbols |
| FR-15 | Audio (wav, mp3) | P5 | Demucs, librosa, Basic Pitch, drum model | Separate package; outputs IR JSON |

### Passes

Each pass implements `run(song, options) -> Song`, is pure (no side effects), and can be chained in any order the user lists.

- **FR-20 quantize** (P1): snap events to a grid (8ths, 16ths, triplets).
- **FR-21 dedupe_bars** (P1): detect identical bars per track so emitters can collapse them.
- **FR-22 detect_sections** (P2): group repeated multi-bar runs into named sections.
- **FR-23 arrange** (P2): for inputs without drums or bass, generate them from a style template (for example lofi, rock, four-on-the-floor).
- **FR-24 transpose, remap_drums** (P2): utilities.
- **FR-25 simplify** (P5): remove ghost notes and very short or quiet events, mainly for audio input.
- **FR-26 detect_tempo** (P5): estimate bpm when the input has none.

### Emitters

- **FR-30 Strudel** (P1): writes a `.js` file that plays on strudel.cc without edits.
  - Maps 1 bar to 1 cycle and sets `setcps(bpm / 60 / beatsPerBar)`.
  - Writes drums as `s("...")`, notes as `note("...")`, chords as `chord("...").voicing()`.
  - Collapses repeated bars with `<...>` and repeat syntax.
  - Emits one named `const` per section and joins them with `arrange()` when sections exist.
  - Adds a comment header with title, source file, and Strudelizer version.
- **FR-31 Sound profiles** (P1): a YAML file maps roles to Strudel sounds and effects (for example bass to `sawtooth` with `lpf(800)`). Ships with default, lofi, and techno.
- **FR-32 MIDI** (P2): writes the IR back to MIDI for round-trip tests and listening in a DAW.
- **FR-33 IR JSON** (P1): any stage can write the IR so it can be inspected or edited by hand.

### CLI and library

- **FR-40** One-shot: `strudelize <input> -o song.js [--profile lofi] [--passes quantize:16,dedupe_bars]`.
- **FR-41** Staged: `strudelize import <input> -o song.ir.json`, `strudelize pass <ir> ...`, `strudelize emit <ir> -o song.js`.
- **FR-42** `strudelize list` shows installed importers, passes, emitters, and profiles.
- **FR-43** Everything the CLI does is available as a Python API (`Pipeline(importer, passes, emitter).run(path)`).
- **FR-44** Errors name the stage, the input location (bar, line, or tab measure), and the fix when one is known.

## Architecture and non-functional requirements

The Song IR is the only contract between stages. Importers, passes, and emitters never call each other directly, so any one can be replaced, added, or run as a separate program.

```
 IMPORTERS                CORE CONTRACT        PASSES                   EMITTERS

 MIDI · P1          ─┐                                                  [Sound profiles]
 Chord sheet · P2   ─┤                                                         │
 Guitar Pro · P3    ─┤    ┌──────────────┐    ┌───────────────────┐            v
 ASCII tab · P3     ─┼──▶ │   Song IR    │──▶ │ quantize          │ ──┬──▶ Strudel .js
 MusicXML · P3      ─┤    │ versioned    │    │ dedupe_bars       │   ├──▶ MIDI
 Audio · P5, Docker ─┘    │ JSON, times  │    │ detect_sections   │   └──▶ IR JSON
 (separate package)       │ in beats,    │    │ arrange, transpose│
                          │ schema-      │    │ simplify,         │
                          │ checked      │    │ detect_tempo      │
                          └──────────────┘    │ (each Song→Song)  │
                                              └───────────────────┘
```

The audio importer lives outside the core package and only hands Song IR JSON to the rest of the pipeline.

### Non-functional requirements

- **NFR-1 Portability:** the core is pure Python 3.10+ on macOS, Linux, and Windows. Core dependencies are limited to mido, PyYAML, and jsonschema.
- **NFR-2 Modularity:** importers, passes, emitters, and profiles register through Python entry points (`strudelizer.importers`, `strudelizer.passes`, `strudelizer.emitters`). The core never imports a plugin by name.
- **NFR-3 Stage independence:** every stage reads and writes IR JSON, so a stage can be rewritten in another language (for example a TypeScript emitter running in the browser).
- **NFR-4 Optional extras:** heavier importers install on demand (`strudelizer[guitarpro]`, `strudelizer[musicxml]`). Audio is a separate package, `strudelizer-audio`, plus a Docker image.
- **NFR-5 Determinism:** the same input and options always produce byte-identical output.
- **NFR-6 Performance:** a 5-minute MIDI song converts in under 2 seconds on a laptop (proposed target).
- **NFR-7 Testability:** each plugin ships golden-file fixtures; the MIDI emitter enables round-trip tests.

### Repository layout

```
strudelizer/
  core/        ir.py, schema.json, time.py, theory.py
  importers/   midi.py, chordsheet.py, guitarpro.py, ascii_tab.py, musicxml.py
  passes/      quantize.py, dedupe_bars.py, sections.py, arrange.py, transpose.py
  emitters/    strudel.py, midi.py, ir_json.py
  profiles/    default.yaml, lofi.yaml, techno.yaml
  styles/      arrange templates (lofi, rock, four_on_floor)
  registry.py, pipeline.py, cli.py
strudelizer-audio/   separate package + Dockerfile (P5)
tests/fixtures/      inputs + expected .js and .ir.json
```

## Success metrics

The targets below are starting proposals, to be tuned once the fixture set exists.

| Metric | Target | How it is measured |
| --- | --- | --- |
| Output plays without edits | 100% of fixtures | Generated `.js` loads and evaluates in Strudel's runtime in CI |
| MIDI round-trip fidelity | 98%+ of notes match after quantize | MIDI in → IR → MIDI out, compared note by note |
| Readability | Output 50%+ shorter than one-string-per-bar | Line count with dedupe on versus off |
| Time to first sound | Under 2 minutes from install | Fresh install, one MIDI file, paste into strudel.cc |
| Core install footprint | Under 20 MB, no compiled ML dependencies | `pip install strudelizer` size |
| New plugin effort | One file, no core changes | Count of files touched when adding an importer |

## Risks and decisions

**Risks**

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Chord sheets and ASCII tabs carry no rhythm or tempo | Output sounds wrong or flat | Required `--bpm` flag, beats-per-chord default of one bar, rhythm hints, and the arrange pass |
| Chord sheet formats vary widely | Parser misses chords or treats lyrics as chords | Support ChordPro first, then chords-over-lyrics with a strict chord-token regex; report unparsed lines |
| Strudel syntax changes | Generated code breaks | Pin a tested Strudel version in CI; keep all syntax in the emitter only |
| Long songs give huge mini-notation strings | Unreadable output | dedupe_bars and sections passes; split each section into its own `const` |
| Audio transcription is noisy | Messy, unusable output | Audio ships last, behind simplify and quantize passes, with clear accuracy expectations |
| Heavy ML dependencies | Breaks portability | Audio lives in a separate package and Docker image that only outputs IR JSON |

**Decisions** (proposed; revisit at the end of P1)

1. **Python only, or a TypeScript emitter too?** Python only through P3. In P4, port just the IR schema and the Strudel emitter to TypeScript, so it can run in the browser next to Strudel. Both implementations must pass the same golden fixtures, which keeps them in sync. Importers stay in Python, since their parsing libraries (mido, PyGuitarPro, music21) live there.
2. **Which chord spellings on day one?** The parser accepts the common spellings: major (`C`), minor (`Cm`, `Cmin`, `C-`), `7`, major 7 (`Cmaj7`, `CM7`, `C^7`, `CΔ`), `m7`, `6`, `m6`, `9`, `add9`, `sus2`, `sus4`, `dim` and `°`, `m7b5` and `ø`, `aug` and `+`, and slash chords (`C/E`). The IR stores one canonical form (root, quality, extensions, bass). The emitter converts it to the spelling Strudel's voicing dictionary accepts (for example `^7`), checked by a fixture test against the pinned Strudel version. A chord the dictionary lacks falls back to explicit stacked notes in `note()`.
3. **General MIDI or Strudel drum names in the IR?** Neither directly. The IR uses its own small, readable vocabulary (`kick`, `snare`, `closed_hat`, `open_hat`, `clap`, `rim`, `tom_low`, `tom_mid`, `tom_high`, `crash`, `ride`). Importers map General MIDI note numbers into it. The sound profile maps it to Strudel names (`bd`, `sd`, `hh`, `oh`, `cp`, `rim`, `lt`, `mt`, `ht`, `cr`, `rd`). This keeps the IR independent of any one output.
4. **Odd time signatures and tempo changes?**
   - Constant meter, including odd ones like 7/8 or 5/4: 1 bar = 1 cycle, with the bar split into its own number of steps. `setcps` uses the time signature's beat unit, so 7/8 at 140 eighth notes per minute gives `setcps(140 / 60 / 7)`.
   - Changing meter: switch to 1 cycle = 1 beat. Each bar is written as its own pattern slowed by its beat count and joined with `arrange()`, for example `arrange([3, barA.slow(3)], [4, barB.slow(4)])`.
   - Tempo: P1 to P3 use one tempo, the one that covers the most bars, and print a warning when the source has others. A later release can handle tempo changes between sections by scaling each section with `.fast(sectionBpm / baseBpm)`. Gradual changes (ritardando, rubato) are flattened by quantize.
5. **Hosted web demo after P5?** Not in scope through P5; the CLI and Python library are enough. After P5, the TypeScript emitter from decision 1 makes a static, fully client-side demo cheap: drop in a MIDI file or paste a chord sheet, then open the result in strudel.cc. Audio stays out of the demo because it needs server-side GPUs.

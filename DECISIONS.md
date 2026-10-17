# Decisions made during P1

These are the choices made where the PRD left room, in addition to the PRD's
own "Decisions" section. Items marked **(IR)** affect the IR format and were
confirmed before implementation. Items marked **review** are the ones most
worth a second look.

## IR format

1. **(IR) A beat is the time signature's denominator unit.** In 7/8 a beat is
   an eighth note and `meta.bpm` counts eighths per minute, so a bar is
   always `numerator` beats long and `setcps(bpm / 60 / numerator)` (Decision 4).
   The MIDI importer converts quarter-note ticks with `ticks / tpq * den / 4`.
2. **(IR) dedupe_bars writes `track.bars`.** This is an optional per-track list
   where entry *i* is the index of the first bar identical to bar *i*. Events
   are left alone. Any pass that changes events must drop `bars`; quantize
   does this.
3. **(IR) `hit` events have an optional `velocity`** (1 to 127), like notes.
4. **Times are normalised fraction strings**, `"0"`, `"3"` or `"7/2"`. The
   schema rejects decimals and negatives, and requires durations to be > 0.
5. **Velocity range is 1 to 127.** 0 is a note-off in MIDI, so it is not a
   valid velocity.
6. **"All fields except events are optional" (FR-6)** applies to the song,
   meta and track levels. A section entry still needs `start_bar` and
   `length`, since a section without them is meaningless; its `name` is
   optional.
7. **Ids and section names must be identifiers** (`^[A-Za-z_][A-Za-z0-9_]*$`)
   so they can become JS names. `x-` prefixed keys are allowed at the song
   and track level for extensions, and they round-trip.
8. **Chord events already carry Decision 2's canonical form** (`root`,
   `quality`, `extensions`, `bass`, plus `symbol` and optional `pitches`),
   so the P2 chord-sheet importer needs no format change.
9. **bpm is rounded to 3 decimals.** MIDI stores tempo as µs per quarter,
   so 70 bpm reads back as 69.99997.

## MIDI importer

10. **Tempo and meter changes:** the importer uses the value that covers the
    most ticks (earliest wins ties) and warns. With constant meter, ticks are
    proportional to bars, so this is Decision 4's "tempo that covers the most
    bars". A changing meter also just warns and uses the dominant meter; full
    support is a later phase.
11. **Bar 1 starts at tick 0.** Pickup bars (anacrusis) are not detected.
12. **Unmapped GM drum keys are dropped** with one warning listing key and
    count (for example cowbell 56, tambourine 54). The mapping is in
    `importers/midi.py:GM_DRUMS`. **review**: P2's `remap_drums` could
    instead map these to the nearest vocabulary drum.
13. **Tracks** are split by (MIDI track, channel). The role comes from the
    first rule that matches:
    1. channel 10 → drums
    2. a track-name keyword (bass / vocal / chord-pad-keys-piano / lead-melody)
    3. GM program 32 to 39 → bass
    4. median pitch below C3 → bass
    5. on average 2 or more notes sounding at each onset → chords
    6. otherwise melody

    **review**: these are heuristics.
14. **Note pairing:** note-ons and note-offs pair first-in first-out per
    pitch, `note_on` with velocity 0 is a note-off, and notes still open
    close at the end of the track.
15. **`meta.source` is the file's basename,** never the full path, so output
    doesn't depend on where the file sits (NFR-5).

## Passes

16. **The quantize grid syntax** is `4`, `8`, `16`, `32`, `64`, `8t`, `16t`,
    combined with `+`. A point snaps to the nearest grid point across all
    grids; ties go to the earlier point, then to the grid listed first.
    Durations snap their end point, with a minimum of one step of the grid
    the start snapped to. Events that land on the same slot (same start and
    pitch/drum/symbol) merge, keeping the longest and loudest.
17. **The one-shot default passes are `quantize:16+8t,dedupe_bars`.** `16+8t`
    keeps both straight 16ths and 8th-note triplets. `--passes ""` turns them
    off.

## Strudel emitter

18. **A note that crosses a bar line is split and re-attacked** in the next
    bar, because each bar is its own cycle of mini-notation. dedupe_bars and
    the emitter share `core.time.slice_bars`, so "identical bars" always means
    identical output. **review**: P2 could use Strudel's `@` across `<…>`
    steps or `.legato` instead.
19. **Mini-notation layout.**
    - Each voice renders on its smallest exact grid (LCM of denominators).
      Durations become `@n`.
    - Rests are written out (`~ ~ ~`) on grids of up to 16 steps, and merged
      (`~@k`) on finer ones.
    - A voice whose steps are all the same becomes `tok*n`.
    - Simultaneous notes of equal length become `[c4,e4,g4]`; overlapping
      notes go into separate `,` voices (first fit).
    - Drum tracks get one voice per drum name.
20. **Collapsing repeats.**
    - Collapsing only happens when dedupe_bars has run. That keeps
      "dedupe on vs off" measurable.
    - Consecutive repeats become `bar!n`. If a sequence repeats with a period
      that divides the song length, only one period is written.
    - Repeats are detected per rendered voice sequence, which refines the
      track-level `bars` map: a crash in bar 1 must not stop the hi-hats
      collapsing.
    - Non-adjacent repeats (A B A C) are written out again; named consts for
      them come with P2's sections.
21. **Long sequences** (more than 4 items) use a multi-line backtick string,
    4 bars per line. Strudel's transpiler treats backtick strings without
    `${}` as mini-notation.
22. **Velocity.**
    - If every event in a track part has the same velocity, nothing is
      written.
    - Otherwise velocities are scaled so the loudest event in that part
      = 1, and the part is written as `stack()` of its voices, each with
      its own step-aligned `.velocity()` (a scalar when constant within the
      voice).
    - The voices have to be split because a `.velocity("a, b")` pattern
      duplicates events.
    - Stacked chord notes take the loudest velocity of the group.
    - **review**: absolute vs relative velocity. Relative was chosen because
      the profile's `gain` already sets the mix.
23. **Chord spellings.** These were checked against the pinned voicing
    dictionary: `maj7→^7`, `m7b5→h7`, `dim→o`, `dim7→o7`, `sus4→sus`,
    `7sus4→7sus`, `aug`, `6`, `m6`, `69`, `9`, `maj9→^9`, `m9`, `add9`, `11`,
    `13`, `7b9`, `mmaj7→m^7`.
    - The dictionary has no `sus2`, `dim`, `ø`, `maj7` or `+`.
    - Slash chords can't be written at all, because `/` is mini-notation's
      slow-down operator.
    - These fall back to an explicit `note()` stack when the chord has
      `pitches`. Without pitches it is an error that names the bar.
24. **Sections:**
    - Each section becomes one `const`, and the song ends with
      `arrange([bars, name], …)`.
    - Gaps between sections become `partN` consts.
    - A section that repeats with identical content reuses its const;
      different content under the same name gets `name_2`.
    - Names that clash with JS keywords or the Strudel functions used in the
      output get a `_part` suffix.
25. **Header comments** give the title, source basename, Strudelizer version
    and profile. There are no timestamps (NFR-5). Output is UTF-8 with LF
    line endings on every OS.

## Profiles

26. **The profile YAML** has `drums.{bank,map,fx}` and
    `roles.<role>.{sound,fx}`.
    - `fx` is an ordered list of single-key maps, so output order is
      deterministic.
    - Missing roles fall back to `other`, then to `triangle`. A missing drum
      map uses Decision 3's names.
27. **Banks were checked against strudel.cc's drum-machine sample map.**
    - Only `RolandTR909` and `LinnDrum` have all 11 of Decision 3's sounds
      (TR-808 has no ride, for example).
    - default and techno use `RolandTR909`; lofi uses `LinnDrum`.
    - Synths are Strudel's built-in `sine`/`square`/`triangle`/`sawtooth`, so
      no `samples()` call is needed.
28. **Profiles register as entry points** whose target is a zero-argument
    callable returning the mapping. `--profile` also accepts a `.yaml` path.

## Pipeline, CLI, validation

29. **Validation runs in `Pipeline`,** not inside each plugin, so
    third-party plugins get it for free. (P1 validated at every stage
    boundary; since P2 it validates at process boundaries, see item 35.)
    - Songs are immutable, so a Song object that has already been validated
      (a pass's output is the next stage's input) is not validated again.
    - The validator inlines the schema's local `$ref`s at load time. It gives
      the same verdicts about a third faster; `schema.json` itself is
      unchanged.
30. **CLI.**
    - `strudelize <input>` is the one-shot form; `import`, `pass`, `emit`
      and `list` are subcommands, chosen by the first word.
    - The emitter is chosen from the `-o` extension (`.json` → `ir_json`,
      anything else → `strudel`).
    - With no `-o`, output goes to stdout (as UTF-8 bytes, LF).
    - Warnings print to stderr as `warning [stage]: …`. Errors print as
      `error [stage] at <location>: …` plus `fix: …`, and exit with 1.

## Tests and tooling

31. **The Node check needs a resolve hook.** `@strudel/core` 1.2.6 imports
    `@kabelsalat/web`, whose package declares its ES module build only in the
    `module` field. Vite (and so strudel.cc) uses that field; Node does not,
    and fails on the named import. `tests/strudel/esm-fix.mjs` points Node at
    the ESM build. Nothing about the generated code changes.
32. **Strudel validity checks more than "doesn't throw":**
    - The whole song (8 cycles) is queried.
    - Drum hits must match the IR exactly, and every IR note must sound at
      the right cycle position.
    - Voiced chords are checked to produce at least 3 notes at their onsets
      (their pitches come from Strudel's dictionary).
    - `cps` is compared with the expected value.
    - Velocities are not compared.
33. **The readability metric is measured on mini-notation text.** The header
    and sound chains are the same with or without dedupe. On the 8-bar
    `multitrack_repeats` fixture, dedupe makes the pattern text 58% shorter
    and the whole file 39% shorter (685 vs 1125 characters).
34. **Fixtures are generated** by `tests/fixtures/make_fixtures.py`, and a
    test checks that it reproduces the checked-in `.mid` bytes. The triplet
    melody has deterministic ±9-tick jitter so quantize does real work.

## Open items (from P1)

- **Manual check.** The output has been checked against Strudel's runtime in
  Node, but not yet listened to on strudel.cc in a browser. Paste one
  generated file there once to confirm the sample banks load.

---

# P1 follow-ups (done at the start of P2)

35. **Validation happens at process boundaries.** This replaces item 29's
    "every stage boundary".
    - The IR is schema-checked when it enters the process (importer output,
      `read_ir`) and when it leaves (`save_ir`, CLI `import`/`pass` output,
      any emitter with `writes_ir`, which is `ir_json`).
    - Passes running in one process are not re-validated unless strict mode
      is on: `--strict`, `Pipeline(strict=True)`, or `STRUDELIZER_STRICT=1`.
      Strict checks every pass's input and output and the emitter's input.
    - Outside strict mode, a pass must still return a `Song`; that cheap
      type check always runs.
    - `tests/conftest.py` sets `STRUDELIZER_STRICT=1`, so the whole suite,
      including CLI subprocesses, runs strict.
    - The validator is compiled once (`lru_cache`, with refs inlined).
      `is_valid` runs first, and `best_match` only runs on failure.
36. **NFR-6 measurement.** `python tests/bench_dense.py` builds a
    deterministic dense 5-minute song (5,923 notes, 150 bars, 4 parts) and
    times the default one-shot pipeline (best of 3 runs, this laptop).

    | | Before (P1) | Now |
    | --- | --- | --- |
    | Default mode | 5.2 s | **1.18 s** (meets the 2 s target) |
    | `--strict` | n/a | 2.16 s |

    Strict mode validates three times (import plus two passes); it is meant
    for tests and debugging.
37. **New drums: `cowbell`, `tambourine`, `shaker`.**
    - Checked against strudel.cc's sample maps: Strudel's default kit
      (`uzu-drumkit`, used when no bank is set) has `cb`, `tb` and `sh`, and
      so do `LinnDrum` and (except `tb`) `RolandTR808`. `RolandTR909` has none
      of them.
    - They are therefore mapped (`cb`/`tb`/`sh`), and the new profile field
      `drums.unbanked` lists drums the bank lacks. Those play from the
      default kit in a separate `s()` pattern without `.bank()`, because
      `.bank("RolandTR909")` would ask for the missing `RolandTR909_cb`.
    - default and techno list all three; lofi (LinnDrum) needs none.
    - Mapping a drum to `null` in a profile drops it with a warning at emit
      time.
    - GM keys: 56 → cowbell, 54 → tambourine, 69/70/82 (cabasa, maracas,
      shaker) → shaker. Other unmapped keys are still dropped at import with a
      warning.
    - Drum velocities are scaled across the whole track, so the banked and
      unbanked patterns stay relative to each other.
38. **(IR) Pickup bars: `meta.pickup_beats`.**
    - **review: field name.** You asked for `pickupBeats`. I used
      `pickup_beats` because every other IR field is snake_case
      (`time_signature`, `start_bar`). Renaming is a one-line change in
      `core/ir.py` and `schema.json` if you prefer camelCase.
    - Event times still start at 0 = the start of the pickup. Bar 1 starts at
      `pickup_beats`, and the value must be shorter than a bar (checked after
      the schema).
    - `core.time.bar_offset` (bar length minus pickup) shifts bar lines for
      `slice_bars`, so in Strudel cycle 0 holds the pickup at its end and
      **bar 1 starts on cycle 1**. The header says so in a comment. quantize
      aligns its grid to bar lines, and dedupe/emitter bar indices use the
      same offset.
    - Bar index 0 is the pickup bar for `sections[].start_bar` and error
      locations ("the pickup bar", "bar 1", …).
    - **MIDI import** detects a pickup written the way notation programs
      export it: a first time signature lasting exactly one bar that is
      shorter than a bar of the next meter (e.g. 1/4 then 4/4). That first
      meter is not reported as a meter change. `--pickup BEATS` overrides
      detection (the importer option `pickup`).
    - **review:** a pickup written as a full first bar with leading rests is
      indistinguishable from a song that starts with silence, so it is not
      detected.
39. **IR version 2, migration from v1.** v2 adds only optional things
    (`meta.pickup_beats` and three drum names), so every v1 document is a
    valid v2 document. `core.ir.migrate()` relabels `"version": "1"` as
    `"2"` on load, before validation. Strudelizer writes v2 only.
    - **Migration note for v1 users:** nothing to do. Old `.ir.json` files
      load as before. Re-saving them writes `"version": "2"`. Tools that read
      the IR must accept the three new drum names and may see `pickup_beats`.
    - Unknown versions fail with "unsupported IR version" and a fix.
    - `tests/fixtures/ir/sections_chords.ir.json` stays at v1 on purpose, so
      the migration runs in every test session.

# P2 decisions

40. **Chord parsing lives in `core/theory.py`** (no library). The grammar is
    root + one of a fixed table of spellings + optional `/bass`.
    - The table holds all Decision 2 spellings plus common extras: maj9, m9,
      69 / 6/9, 11, 13, 7b9, 7#9, 7sus4, mmaj7, madd9, 5.
    - Canonical form:
      - `quality` is one of maj, m, 7, maj7, m7, 6, m6, sus2, sus4, 7sus4,
        dim, dim7, m7b5, aug, mmaj7, 5.
      - `extensions` holds 9, 11, 13, b9, #9 or add9. For example, C9 =
        quality 7 + [9], Cadd9 = maj + [add9].
      - `bass` holds the slash note.
    - `chord_name()` turns that back into a short name (`9`, `maj9`, …) that
      emitters key on.
    - `H` (German B) is not accepted.
41. **Default chord voicing.** Close position with the root in octave 3, and
    a slash note in octave 2 below it. The importer stores it in `pitches`, so
    every chord can fall back to explicit notes.
42. **Strudel chord spellings re-checked** against the pinned dictionary.
    Added `7#9`, `madd9`, `5`, and **`sus2 → 2`**: the dictionary's `C2`
    voices C-D-G with no third, which is a sus2.
    - This changes the P1 fixture `sections_chords.js`: Csus2 is now voiced
      from the dictionary instead of as a note stack.
    - Slash chords still use explicit `pitches`, since the dictionary can't
      voice a bass note.
43. **The chord sheet importer reads all three formats line by line,** in any
    mix.
    - **Timing.** A chord in ChordPro or chord-over-lyrics lines lasts
      `--beats-per-chord` beats (default one bar). In bar lines, a bar splits
      evenly among its tokens. `/` or `.` holds the previous chord for a slot,
      `%` repeats the previous bar, an empty bar holds the chord, `|: :|`
      repeats within a line, and a trailing `x2` repeats the line.
    - **Pickup.** It comes from `{x_pickup: N}` or `--pickup`, with
      `--pickup` winning. The first chord, or first bar, then lasts the
      pickup.
      - `x_pickup` is the canonical name, because the ChordPro spec reserves
        the `x_` prefix for custom directives and standard ChordPro has no
        pickup directive.
      - `{pickup: N}` is accepted as an alias for sheets that are not strict
        ChordPro (the chords-over-lyrics and bar-line fixtures use it, so both
        spellings stay tested).
      - (Changed in P3: P2 treated `{pickup}` as primary.)
    - **Tempo.** `--bpm` wins over `{tempo}`. With neither, 100 bpm with a
      warning. bpm counts beats of the time signature's denominator, like the
      IR.
    - **Meter.** `{time: 3/4}` must come before the first chord, since meter
      changes aren't supported.
    - **Sections:**
      - The labels are `[Verse]`, `Chorus:`, a known label word alone on a
        line (intro, verse, pre-chorus, chorus, bridge, outro, solo, …,
        optionally numbered), and `{start_of_chorus|verse|bridge}` /
        `{soc}`, `{sov}`, `{sob}` with an optional label.
      - `{chorus}` replays the last chorus.
      - A section that starts mid-bar holds the previous chord to the bar
        line, and the song's last chord holds to the final bar line.
      - Names become identifiers: "Verse 2" → `verse_2`.
    - **Title.** `{title}`, else the first plain-text line before any chord,
      else the file name.
    - **Unparsed lines** are reported as a warning that names the line
      number and the bad tokens, and are skipped whole (not half-read). That
      covers:
      - unknown directives;
      - bar lines with a non-chord token;
      - `[...]` inline brackets that aren't chords (`[*text]` annotations are
        allowed);
      - chord-like lines with a bad token. "Chord-like" means every token
        starts with a note letter and has a digit or chord symbol in it, like
        `Hm7`; plain words like `Bad` or `Day` don't count.

      Lyric lines are never reported.
    - **Out of scope.** `{start_of_tab}` blocks are skipped with a warning
      (tabs are P3), and `{new_song}` is reported because there's one song
      per file.
44. **Styles are YAML data** in `strudelizer/styles/`, registered through a
    new `strudelizer.styles` entry-point group, the same way as profiles.
    `--style` takes a name or a `.yaml` path. A style has:
    - per-meter step patterns for drums, bass rhythm and an optional chord
      rhythm (`x` hit, `X` accent, `g` ghost, `.` rest);
    - a bass rule: `root`, `root_fifth` (the fifth is taken from the chord,
      so a diminished chord gets a b5) or `root_octave`, plus an octave;
    - velocities.

    lofi, rock and four_on_floor each cover 4/4 and 3/4. Other meters fail
    with a fix that names the covered meters.
45. **What arrange does.**
    - It generates only missing parts: drums if there's no drums track, and
      bass if there's no bass track and the song has chord symbols. Without
      chords it warns and skips the bass.
    - The bass also re-strikes at every chord change, so it never holds a
      wrong note across a change.
    - With a chord rhythm, chords are re-struck on it.
    - Generated parts skip the pickup bar.
    - **Slash chords:** when a bass part plays, the bass plays the slash note
      and the chord's `pitches` become the chord without that pitch class
      (unless that would leave fewer than 2 notes). For C/E that is C-G with
      no E, the usual "don't double the bass note's third". The `bass` field
      stays, so the emitter writes the explicit notes.
    - Without arrange, the importer's voicing keeps the slash note at the
      bottom, so nothing is lost.
    - `--style X` puts `arrange:style=X` first in the pass list. Combining it
      with an explicit `arrange` pass is an error.
46. **detect_sections** cuts the song (after a pickup bar, which becomes its
    own `pickup` section) into equal blocks of 16, 8, 4 or 2 bars.
    - It uses the longest size where at least two blocks repeat and at least
      half the blocks are repeats. `detect_sections:4` forces a size.
    - Blocks equal across all tracks share a name (`part_a`, `part_b`, …).
    - If nothing repeats, the song is left without sections. Sections an
      importer set are never touched.
    - It is opt-in: it is not in the default passes, because for short loops
      `arrange()` with consts is longer than one collapsed pattern.
      **review**
47. **transpose** shifts notes, chord pitches, roots, slash notes, symbols
    (the original spelling suffix is kept, e.g. `Bb6/9` → `C6/9`) and
    `meta.key`.
    - New names use the new key's convention: flats for F, Bb, Eb, Ab, Db
      and their relative minors.
    - With no key, each chord keeps its own accidental style.
    - Leaving the MIDI range is an error naming the track and bar.
    - `bars` is kept, since a uniform shift preserves equality.
48. **remap_drums** takes a YAML/JSON file of `drum: drum` (or `null` to
    drop), with names checked against the vocabulary. Hits that collide merge,
    keeping the loudest, and `bars` is dropped. It lives in its own
    `passes/remap_drums.py`.
49. **MIDI emitter (FR-32).**
    - Type 1, 480 tpq, a conductor track (title, tempo, time signature, key
      if mido accepts it), and one MIDI track per IR track named by its id,
      so the importer gets the same ids and roles back.
    - Programs come from the `gm:N` hint, else a per-role default.
    - Drum hits go on channel 10 as 32nd notes, with keys chosen so the
      importer maps each back to the same drum.
    - Chords become their `pitches` (or a voicing from root+quality).
    - A pickup is written as a short first time signature.
    - Times that aren't whole ticks are rounded, with one warning.
    - `Emitter` gained `binary` (emit returns bytes) and `writes_ir`.
50. **The round trip** is now MIDI → IR → quantize → MIDI emitter → IR,
    compared note by note with an independent reading of the source: **100%**
    on all 6 MIDI fixtures (target 98%). It also checks that tempo, meter,
    pickup, key and track ids/roles survive.


# P3 decisions (tabs and notation)

## Housekeeping

51. **Git.** The repo now has `.gitignore` and `.gitattributes`. `* text=auto eol=lf`
    is required because the golden tests compare bytes and `core.autocrlf` is on
    here. MIDI, GP and `.mxl` fixtures are marked binary. Commits carry no
    attribution trailer.
52. **`scripts/check.py`** runs lint (pyflakes), the tests in strict mode and the
    Strudel check (it runs `npm ci` on the first run). The full run refuses to start
    without the guitarpro and musicxml extras, so their tests cannot silently skip;
    `--allow-missing-extras` overrides that. The Makefile only calls it. pyflakes and
    httpx are in the `dev` extra; `all` = guitarpro + musicxml + ui + dev.
53. **Commits were not made after each P3 milestone as asked.** A second session
    building the web UI was committing to the same branch and staging into the same
    git index while I worked. To avoid sweeping its files into my commits, I built
    P3 in a private index (HEAD plus only my files) and committed it once, with a
    compare-and-swap on `main`. Its two UI commits come before P3 in the history.
    **review**: if you want P3 split into milestones, it can be re-cut from
    `be4856c`.

## Plugins behind optional extras

54. **Entry points name their extra**, e.g.
    `guitarpro = "...:GuitarProImporter [guitarpro]"`, and the plugin class lists
    `requires = ("guitarpro",)`.
    - `registry.available()` counts the plugin only when those modules can be
      found (`importlib.util.find_spec`, nothing is imported).
      `registry.unavailable()` lists the rest.
    - `strudelize list` shows `(not installed; pip install "strudelizer[guitarpro]")`,
      and opening a `.gp5` without the extra fails with that command as the fix.
    - Plugin modules import PyGuitarPro or music21 inside `load()`, so a MIDI
      conversion never pays music21's import time.
    - A plugin behind an extra that cannot even be loaded counts as not installed,
      so it never breaks other conversions.
55. **Shared code moved to `core/`,** because importers must not import each other
    (PRD architecture):
    - the GM drum map, the reverse map and the role heuristic → `core/gm.py`;
    - the dominant-tempo/meter rule → `core.time.dominant`;
    - tab parsing → `core/tab.py`, used by both the tab and chord-sheet importers.

## ASCII tabs (FR-13)

56. **What counts as tab.**
    - A staff line is an optional string label, then `|`, `:` or `-`, then only tab
      characters.
    - Labelled lines need at least one dash; unlabelled lines need at least three,
      so prose with a hyphen is not read as tab.
    - 4 to 7 consecutive staff lines form a block. Other block sizes, and lines that
      are mostly dashes but contain foreign characters, are reported with their
      line numbers.
    - A `.txt` file is claimed by `ascii_tab` only when tab lines make up at least
      half its non-empty lines; otherwise the chord-sheet importer reads it and
      imports its tab blocks.
57. **Tuning.**
    - Labels give each string's pitch class. The octave is the one closest to
      standard tuning for that string count: 4-string bass E1 A1 D2 G2, 5-string
      B0 + bass, 6-string E2…E4, 7-string B1 + guitar. A low `D` on a 6-string tab
      is therefore D2 (drop D).
    - `--tuning` or a `Tuning:` line overrides the labels: names lowest first
      (`D A D G B E`), with octaves (`D2 A2 …`), or a few named tunings (drop d,
      drop c, half step down, open g/d/e, dadgad).
    - Without labels or an option, the tab is in standard tuning.
58. **Rhythm.** `--tab-rhythm` defaults to `even8`: every column that holds a note is
    an eighth note, back to back across the whole tab, and bar lines don't reset
    the count. `even16` is the same with sixteenths. `columns` places notes
    proportionally inside each `|`-delimited bar (a block without bar lines is one
    bar). A note lasts until the next note column. **review**: even-rhythm modes
    ignore bar lines, so a bar with fewer than 8 note columns borrows from the next.
59. **Techniques.** `h p b r / \ ~ ^ ( ) < > s t =` are ignored, and the fret numbers
    around them are kept (`8b10` gives both 8 and 10). A dead note (`x`) is dropped
    but keeps its rhythmic slot, so the riff doesn't shift. A trailing `x2` after the
    last bar line repeats the block.
60. **Chord sheets with tabs** import their `{start_of_tab}` blocks (with an
    optional label, which becomes a section) and bare tab blocks.
    - A tab block starts on a bar line, takes whole bars, and the chords resume
      after it.
    - The tab becomes its own track (`guitar` or `bass`).
    - **`{capo: N}` / `--capo` now transposes the chords too.** Chords in a capo
      sheet are written as shapes, and a tab with a capo sounds higher, so applying
      the capo to only one of them would make them clash. Roots, bass notes,
      symbols and `meta.key` are respelled in the new key. P2 ignored `{capo}`.
      **review**

## Guitar Pro (FR-12)

61. **Unfolding.** PyGuitarPro's `repeatClose` is the number of jumps back (GP5
    stores the total plays and the reader subtracts one), and `repeatAlternative`
    is a bitmask of the passes a measure is played on. A repeat with no open sign
    goes back to the start. Markers become sections in played order (a marker
    inside a repeat starts a section on each pass); they are dropped when the meter
    changes, because bar indexes would not line up.
62. **Techniques, one by one** (as specified):

    | Technique | Treatment |
    | --- | --- |
    | Tied notes (`NoteType.tie`) | Extend the last note on the same string in the same voice, across bar lines and repeats. |
    | Dead notes | Dropped. |
    | Grace notes | The ornament is dropped and the main note is kept. GP stores a grace note as an effect on the note it decorates, not as a note of its own, so dropping the note would lose the melody. |
    | Bends, slides, hammer-ons, vibrato, harmonics, palm mutes, … | Ignored: the note plays at its fret pitch. |

    Counts of dropped dead notes and grace ornaments are reported in one warning.
63. **Pitch and roles.**
    - Pitch is open string + fret + `track.offset` (the capo).
    - A track is percussion if `isPercussionTrack` or it is on channel 10, and its
      fret numbers are GM keys.
    - Roles come from the shared heuristic. A 4- or 5-string track tuned below E2
      counts as bass.
    - Velocities come from GP dynamics. The key comes from the first measure's key
      signature.

## MusicXML (FR-14)

64. **music21 does the musical work.**
    - `expandRepeats()` unfolds repeats and endings, and `stripTies()` merges tied
      notes; both behaved correctly on the fixture.
    - Grace notes and rests are dropped.
    - Unpitched notes become drum hits when their instrument gives a GM key
      (`percMapPitch`), else they are dropped with a count.
    - **review**: unpitched percussion has only been coded against music21's API,
      not tested with a fixture. The P3 percussion coverage is in the GP fixture.
65. **Harmony symbols.**
    - A ChordSymbol becomes text for the core grammar from its root, its MusicXML
      `kind` (a table maps about 25 kinds to spellings) and its bass: `F/A`,
      `Gsus4`, `Fmaj7`.
    - music21 writes flats as `-` (`B-`), which would read as minor, so roots are
      converted to `b`.
    - An unknown kind is kept as a chord with explicit pitches, or dropped with a
      count.
    - Each symbol lasts until the next one, and all symbols go on one `chords`
      track.
66. **Pickup.** A first measure with `paddingLeft` (an implicit short measure) is a
    pickup of `bar - paddingLeft`. Tempo comes from metronome marks and meter from
    time signatures, both by the dominant rule. `.mxl` gives byte-identical output
    to the same score uncompressed.

## Tied notes in the Strudel emitter (investigation)

67. **The problem.** Each bar is one cycle (one item of `<...>`), so a note that
    crosses a bar line had to be split and played again. Ties are common in GP and
    MusicXML, and held chords (`| EbΔ | |`) are common in chord sheets.

    **Options, using only Strudel 1.2.6 features:**

    1. **Keep re-attacking** (P1/P2). Simple and readable, but wrong for ties.
    2. **A `.clip()` / `.legato()` pattern per voice.** Let the last note of a bar
       sound past the cycle end, and silence its continuation in the next bar. This
       works in Strudel, but it needs a second step-aligned pattern per voice (like
       `.velocity()`), and the next bar must also drop the re-attacked tail. That
       roughly doubles the text and is hard to read or edit by hand.
    3. **One long sequence per track:** `note("[bar1 bar2 …]").slow(n)`. `@`
       weights then span bar lines naturally, but the per-bar layout, `bar!n` and
       loop collapse are lost, which works against Goal 2.
    4. **Multi-cycle steps inside `<...>`.** Write the bars joined by a tie as one
       step with weight k: `<… [c4 d4 e4 f4@2 g4 a4 b4]@2 …>`. Checked in the
       pinned runtime: `<x@2 y>` plays x over two cycles at the normal rate, the
       held note has one event whose span crosses the cycle boundary, and it
       combines with `!n` and step-aligned `.velocity()`. The layout stays one item
       per bar unless a tie joins bars, and collapse still works.
    5. **`_` elongation** is equivalent to `@` inside one sequence, so it is the same
       as option 4.

    **Recommendation: option 4. It is implemented**, because it is about 60 lines
    and the output stays readable. Details:
    - Spans are computed per part of a track (notes, chord symbols; drums never tie).
    - A run is capped at `MAX_TIE_BARS = 4`, and a section start always breaks it.
      Longer holds re-attack at the break.
    - `!n` is used only for one-cycle items; `@k` items repeat by writing them
      again.
    - `core.time.slice_spans` generalises `slice_bars` to spans of any length.
    - The validity test expects onsets only where the emitter actually splits.
    - `dedupe_bars` and the IR are unchanged: `bars` still describes single bars.

    This changed four P1/P2 goldens: the tied `g2` in `bassline.js`, and `Eb^7!2`
    becoming `Eb^7@2` (one held chord) in three Night Train outputs.
68. **NFR-6 with P3 (review).** The dense 5-minute benchmark took 1.9 s with P3 code
    in a quiet moment. During this session the same code measured anywhere from
    1.9 s to 9.5 s, because another session was building on the same machine, so
    the numbers are not reliable. Re-run `python tests/bench_dense.py` on an idle
    machine to confirm the 2 s target still holds; tie spans add one pass over the
    events per track.

## Tests

69. **Fixtures**, all original and made in code or by hand:
    - `tabs/riff.txt`: drop D, hammer-on, dead note, bend/slide/vibrato, `x2`, a
      broken line;
    - `tabs/capo_waltz.tab`: capo 2, 3/4, `columns` rhythm;
    - `tabs/walking_bass.tab`: a 4-string bass;
    - `sheets/lantern_riff.cho`: ChordPro with a labelled `{start_of_tab}`, a bare
      tab block and `{capo: 2}`;
    - `gp/song.gp5`, from `make_gp_fixtures.py`: drop-D rhythm guitar, a lead with
      capo 3, ties across bar lines, a triplet, a grace note and a dead note, a
      4-string bass, a percussion track, a repeat with 1st/2nd endings, and
      markers;
    - `musicxml/score.musicxml` (hand-written): a pickup, ties across bar lines, a
      repeat with 1st/2nd endings, and harmony symbols including F/A;
      `score_compressed.mxl` is built from it by `make_mxl.py`.

    The generators are checked to reproduce the committed bytes.
70. **The P3 gate round trip** is tab/GP/MusicXML → IR → quantize → MIDI emitter →
    IR, per track. Every pitch must match exactly (as a multiset), and at least 98%
    of (pitch, start, duration) must match. All six notation fixtures give 100%.
    Tests for the extras skip cleanly without them; `scripts/check.py` insists on
    them.

# P4 decisions so far (packaging, plugin gate, CI)

71. **Licence: MIT** (your choice). `LICENSE` names "pierre-codes" (the git author
    name) as the copyright holder. `pyproject.toml` uses PEP 639 fields
    (`license = "MIT"`, `license-files`), which need setuptools >= 77; the wheel
    carries `License-Expression: MIT` and `licenses/LICENSE`. There is no licence
    classifier, because PEP 639 forbids using both. **review**: put your real name
    in `LICENSE` if you prefer.
72. **Metadata.**
    - Classifiers: Alpha, console, Python 3.10-3.13, the audio and MIDI topics.
      Keywords are set.
    - `authors` gives the name only, no email, because PyPI metadata is public.
    - No `[project.urls]` yet, since the repo has no remote.
73. **Version 0.3.0** (P1-P3 shipped), set in one place: `strudelizer.__version__`,
    which `pyproject.toml` reads (`dynamic = ["version"]`).
    - FR-30 puts the version in every generated header, so the bump changed all 29
      golden `.js` files in that one line and nothing else.
    - The emitter test now reads the version instead of hard-coding it.
74. **The README's plugin example was broken by P3 and is fixed.** It claimed
    `.tab`, which the built-in `ascii_tab` importer now reads; importers are tried
    in name order, so the plugin never ran. It is now a `.frets` importer. The
    README now explains that a plugin sharing an extension with a built-in needs
    `--importer` or a content-sniffing `can_handle()`. **review** for P4: a
    plugin-priority rule may be worth adding.
75. **Plugin gate test** (`tests/test_plugin_gate.py`).
    - It reads the plugin code and entry point straight out of README.md, so the
      docs cannot drift.
    - It writes a real wheel (with RECORD hashes), creates a venv with
      `--system-site-packages` (so the venv sees the installed Strudelizer), and
      `pip install --no-index --no-deps`es the wheel. No network is used, and
      nothing is installed into your environment.
    - It then runs `strudelize list` and a conversion inside the venv, and
      evaluates the output in Strudel.
    - A second entry point behind a missing extra must show the
      `pip install "my-frets[pro]"` hint.
    - It takes about 40 s, mostly venv creation.
76. **`scripts/check.py` gained two checks.**
    - `package` builds the sdist and wheel (`python -m build`, now in `dev`) and
      checks the wheel's contents and METADATA.
    - The lint step parses every file with the Python 3.10 grammar
      (`ast.parse(feature_version=(3, 10))`), because only 3.13 is installed
      here.
    - The full run is lint → tests → Strudel → package.
77. **CI** (`.github/workflows/ci.yml`):
    - It runs `python scripts/check.py` on ubuntu, macos and windows × Python 3.10
      and 3.13, with fail-fast off, pip and npm caches, Node 22, and every extra
      installed.
    - Line endings on the Windows runner are safe because `.gitattributes`
      forces LF.
    - **Not run yet:** the repo has no remote. Python 3.10 itself has never run
      this code; only its grammar has been checked.
78. **The UI wheel bundles AGPL code (review before any release).**
    `strudelizer_ui/static/strudel/` (a patched `@strudel/repl` 1.2.6, which is
    AGPL-3.0-or-later) is included through
    `package-data "strudelizer_ui" = ["static/**/*"]`, so a wheel would distribute
    it next to MIT code. Options:
    - (a) ship the UI as a separate distribution under the AGPL, with its source
      and the patch;
    - (b) load Strudel from a CDN at runtime instead of vendoring it, so nothing
      is redistributed (the UI then needs a network connection);
    - (c) keep it in this wheel, with a third-party notice, the AGPL text and the
      source offer for that file. Whether the UI's own frontend then becomes AGPL
      is a legal question.

    This belongs to the UI work, so I have not changed it.

# UI decisions (the local web app)

79. **Shape: a separate top-level package, `strudelizer_ui`, behind the `[ui]`
    extra.** FastAPI, uvicorn and python-multipart are listed only there, so a
    core install is unchanged. The package's `__init__` imports nothing from
    FastAPI, so `strudelize ui` can tell "the extra is not installed" from "the
    UI is broken". The frontend is built into `strudelizer_ui/static/`, which the
    app serves; `pyproject.toml` ships it as package data.
80. **The only change to `strudelizer/` is twelve lines of CLI.** `ui` joins
    `COMMANDS`, gets a subparser (`--host`, `--port`, `--no-browser`) and a
    handler that imports `strudelizer_ui.server` lazily and turns `ImportError`
    into the usual `StrudelizerError` with `pip install -e ".[ui]"` as the fix.
    Nothing else in the core knows the UI exists. (Asked and agreed before
    building; the alternative was a second console script, which would have left
    `strudelize ui` saying "unknown command".)
81. **Option metadata lives in the UI, not in the registry.** A plugin just reads
    the keys it cares about out of `options`, so there is nothing to draw a
    control from. `strudelizer_ui/options.py` describes each shipped option as
    `{name, label, type, default, help, group, choices|choices_from, ...}`, with
    three levels of knowledge, most specific first:
    1. a plugin's own `options` attribute (any plugin can opt in),
    2. this table, for what ships with Strudelizer,
    3. neither: `/api/plugins` marks the plugin `custom` and the panel offers a
       `key=value` box, so a newly installed plugin still works.

    `label` is the musician's word and `help` carries the technical spelling
    (`--bpm`, `quantize:16+8t`), which the UI shows as the tooltip. The same
    table names the plugins themselves ("Tidy up the timing" for `quantize`), so
    **the frontend contains no list of plugin names at all**. An option with no
    description is not the same as a plugin with no options: `[]` means "none",
    `null` means "unknown".
82. **Everything the UI knows comes from `/api/plugins`**, including the default
    pass list (`parse_pass_spec(DEFAULT_PASSES)`) and the default emitter (read
    off `Pipeline`'s signature), so the page starts where `strudelize` starts and
    follows it if that changes.
83. **The IR travels to the browser and back.** `/api/import` returns it,
    `/api/convert` and `/api/export` take it, and it is schema-validated every
    time it comes back in (stage `import:ir`), exactly as the CLI validates a
    `.ir.json`. The browser is therefore just another pipeline caller, and the
    song view reads the real IR rather than a summary invented for it.
84. **Conversions are serialised on one thread.** `warnings.catch_warnings` swaps
    a process-global filter list, so two conversions in parallel would steal each
    other's warnings. Every endpoint is `async def`, which keeps it on the event
    loop thread; a thread pool would need a lock instead. Each response carries
    the warnings that its own stage produced.
85. **Problems are the CLI's words.** `report.py` renders
    `error [stage] at <location>: <message>` plus `fix:` verbatim, and also sends
    the parts separately. It pulls a `line N` or `bar N` out of the message with
    a regex, which is what makes a problem clickable: a line selects itself in
    the paste box, a bar scrolls the code to itself.
86. **An upload is written into a temporary directory under the user's own file
    name**, so `meta.source` and the error locations read `night_train.txt`, like
    the CLI. The temp path is stripped out of any error that mentions it. Files
    never leave the machine, and nothing is kept after the request.
87. **Frontend: Vite + TypeScript + Preact, about 40 kB.** No router (one page),
    no component library, one store in `state.ts`, plain CSS with custom
    properties for the two themes. Imports are debounced 400 ms and conversions
    250 ms, each with an `AbortController` and a sequence guard, so dragging a
    number box does not queue up requests. An importer option re-imports;
    anything else only re-converts.
88. **Playback is the real Strudel REPL, vendored.** `@strudel/repl` 1.2.6 is
    pinned to the Strudel the repo's golden-file tests evaluate against, copied
    into the app's own origin by `scripts/vendor-strudel.mjs` (it resolves its
    clock worker against `document.currentScript`, so it cannot be bundled). The
    page talks to the `<strudel-editor>` component's `editor` (a StrudelMirror):
    `setCode` then `evaluate` only if it is already playing, so changing an
    option while the music runs swaps the pattern without stopping it. The
    editor's own theme follows the page's.
89. **Upstream bug, patched in the vendor step.** 1.2.6's prebake fetches its
    sample indexes from `raw.githubusercontent.com/felixroos/dough-samples/main/`,
    where `uzu-drumkit.json` no longer exists; one 404 rejects the whole
    `Promise.all`, `evaluate()` throws and *nothing* plays. The vendor script
    rewrites that host to `https://strudel.b-cdn.net/` (the host Strudel itself
    now uses; same files, each carrying its own `_base`) and fails loudly if a
    future version no longer contains the string, so the patch cannot rot
    silently. Verified in Chromium: before, `started: false` and console errors;
    after, it plays with a clean console.
90. **"Open in strudel.cc" uses the share format from `code2hash` in
    `@strudel/core`**: the UTF-8 bytes in base64, URL-encoded, after the `#`.
91. **Mute and solo regenerate the code without those tracks**, through a
    `tracks` filter on `/api/convert`, rather than editing what the user sees.
    The filter runs after the passes, so it names the tracks the emitter sees -
    including the drums and bass that `arrange` just added.
92. **The song view numbers bars the way Strudelizer's messages number them**:
    with a pickup, cycle 0 is "the pickup bar" and bar 1 is cycle 1; without one,
    cycle 0 is bar 1. "bar 7" in a warning and bar 7 on the ruler are the same
    bar.
93. **Clicking a bar finds the code by section.** It looks up the section the bar
    is in and finds `const <section> =`, then narrows to the line inside a
    multi-line `<...>` pattern. A song with no sections (most MIDI) has nothing to
    point at, so clicking a bar does nothing; clicking a track lane still finds
    that track's pattern. This reads the emitted text rather than reimplementing
    the emitter's layout, so it degrades to "no highlight" instead of lying.
94. **Tests.** `tests/test_ui_api.py` (34 tests) covers every endpoint against the
    existing fixtures, including the error cases, and checks that an export of
    the converted IR is byte-identical to the golden `night_train.rock.js`.
    `strudelizer_ui/frontend/tests/ui.spec.ts` (6 tests) drives the built page in
    Chromium against a real server: a MIDI file plays and saves in all three
    formats, a pasted sheet re-converts when an option changes, a problem points
    at its source line, a bar points at its code, an unreadable file reports like
    the CLI, and the page works at tablet width. Console errors fail the test.
    `python scripts/check.py ui` builds the frontend and runs them.

    **review**: those browser tests need the network, because Strudel fetches its
    samples. They are part of the full `check.py` run, so a fully offline machine
    will see them fail.
95. **review: hand edits are overwritten when an option changes.** The editor is
    the user's to type in, and "Reset to generated" puts the generated code back,
    but the next automatic conversion also replaces it, with only the "edited"
    badge as a warning beforehand. Alternatives are to stop auto-converting once
    the code is dirty, or to ask. Saving always matches what is in the editor.
96. **Known gaps, deliberately.** The page converts one song at a time and keeps
    nothing between visits except the theme. There is no undo beyond the
    editor's own. Two browser tabs on the same server are not isolated from each
    other, which is as safe as it needs to be for localhost.

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
    - **Pickup.** It comes from `{pickup: N}` (or `{x_pickup: N}`, the
      ChordPro custom-directive form) or `--pickup`, with `--pickup` winning.
      The first chord, or first bar, then lasts the pickup. There is no
      standard pickup notation in chord sheets, so this directive is my
      invention. **review**
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

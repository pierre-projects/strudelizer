"""Standard MIDI file importer (FR-10)."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.gm import GM_DRUMS, guess_role, slug
from ..core.ir import Hit, Meta, Note, Song, Track
from ..core.time import dominant
from ..registry import Importer

STAGE = "import:midi"
DRUM_CHANNEL = 9  # GM channel 10, zero-based

DEFAULT_TEMPO = 500000  # microseconds per quarter = 120 bpm


class MidiImporter(Importer):
    """Standard MIDI files (.mid, .midi); GM channel 10 becomes drum hits."""

    name = "midi"
    extensions = (".mid", ".midi")

    def can_handle(self, path: str | Path) -> bool:
        path = Path(path)
        if path.suffix.lower() in self.extensions:
            return True
        try:
            with path.open("rb") as fh:
                return fh.read(4) == b"MThd"
        except OSError:
            return False

    def load(self, path: str | Path, options: Mapping[str, Any]) -> Song:
        import mido

        path = Path(path)
        try:
            mid = mido.MidiFile(str(path), clip=True)
        except FileNotFoundError:
            raise StrudelizerError(STAGE, "file not found", location=str(path)) from None
        except (OSError, EOFError, ValueError, KeyError, IndexError) as exc:
            raise StrudelizerError(
                STAGE,
                f"not a readable MIDI file ({exc})",
                location=str(path),
                fix="re-export the file from your DAW as a Standard MIDI File (type 0 or 1)",
            ) from None
        if mid.type == 2:
            warn(STAGE, "type 2 MIDI file: all sequences are read as if they play together")
        return _convert(mid, path, options)


# ---- conversion ---------------------------------------------------------------


def _absolute(track) -> Iterable[tuple[int, Any]]:
    tick = 0
    for msg in track:
        tick += msg.time
        yield tick, msg


def _detect_pickup(meters: list[tuple[int, tuple[int, int]]], tpq: int):
    """A pickup is written as a first time signature that lasts exactly one
    (short) bar, followed by the real meter, e.g. 1/4 then 4/4. Returns
    (pickup length in ticks, remaining meter changes) or (0, meters)."""
    changes = sorted(meters, key=lambda m: m[0])
    if len(changes) < 2 or changes[0][0] != 0:
        return 0, meters
    (_, (n1, d1)), (tick, (n2, d2)) = changes[0], changes[1]
    first_bar = n1 * tpq * 4 // d1
    main_bar = n2 * tpq * 4 // d2
    if tick == first_bar and tick < main_bar:
        return tick, [(t - tick, m) for t, m in changes[1:]]
    return 0, meters


def _convert(mid, path: Path, options: Mapping[str, Any]) -> Song:
    tpq = mid.ticks_per_beat
    tempos: list[tuple[int, int]] = []
    meters: list[tuple[int, tuple[int, int]]] = []
    keys: list[tuple[int, str]] = []
    names: dict[int, str] = {}
    programs: dict[tuple[int, int], int] = {}
    # (track, channel) -> list of (start_tick, end_tick, pitch, velocity)
    notes: dict[tuple[int, int], list[tuple[int, int, int, int]]] = defaultdict(list)
    end_tick = 0

    for t_index, track in enumerate(mid.tracks):
        open_notes: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        last_tick = 0
        for tick, msg in _absolute(track):
            last_tick = tick
            kind = msg.type
            if kind == "set_tempo":
                tempos.append((tick, msg.tempo))
            elif kind == "time_signature":
                meters.append((tick, (msg.numerator, msg.denominator)))
            elif kind == "key_signature":
                keys.append((tick, msg.key))
            elif kind == "track_name" and t_index not in names:
                names[t_index] = msg.name.strip()
            elif kind == "program_change":
                programs.setdefault((t_index, msg.channel), msg.program)
            elif kind == "note_on" and msg.velocity > 0:
                open_notes[(msg.channel, msg.note)].append((tick, msg.velocity))
            elif kind == "note_off" or (kind == "note_on" and msg.velocity == 0):
                stack = open_notes.get((msg.channel, msg.note))
                if stack:
                    start, velocity = stack.pop(0)  # FIFO pairing
                    notes[(t_index, msg.channel)].append((start, tick, msg.note, velocity))
        for (channel, pitch), stack in open_notes.items():
            for start, velocity in stack:  # never released: close at track end
                notes[(t_index, channel)].append((start, last_tick, pitch, velocity))
        end_tick = max(end_tick, last_tick)

    tempo, tempo_changed = dominant(tempos, DEFAULT_TEMPO, end_tick)
    pickup_ticks, main_meters = _detect_pickup(meters, tpq)
    (num, den), meter_changed = dominant(main_meters, (4, 4), max(end_tick - pickup_ticks, 0))
    scale = Fraction(den, 4)  # quarter-note ticks -> denominator-unit beats

    def beats(tick: int) -> Fraction:
        return Fraction(tick, tpq) * scale

    pickup = beats(pickup_ticks) if pickup_ticks else None
    if options.get("pickup") is not None:  # user override, in beats
        pickup = Fraction(str(options["pickup"])) or None
    if pickup is not None and not 0 < pickup < num:
        raise StrudelizerError(
            STAGE,
            f"pickup of {pickup} beats does not fit in a {num}/{den} bar",
            location=str(path),
            fix=f"use a pickup between 0 and {num} beats (exclusive)",
        )

    qbpm = 60_000_000 / tempo
    bpm = round(qbpm * den / 4, 3)
    bpm_value: float | int = int(bpm) if bpm == int(bpm) else bpm

    if tempo_changed:
        values = sorted({round(60_000_000 / t, 2) for _, t in tempos})
        warn(
            STAGE,
            f"tempo changes found ({', '.join(f'{v:g}' for v in values)} quarter-note bpm); "
            f"using the dominant tempo {qbpm:.6g} for the whole song "
            "(tempo changes are supported in a later release)",
        )
    if meter_changed:
        values = sorted({f"{n}/{d}" for _, (n, d) in main_meters})
        warn(
            STAGE,
            f"time signature changes found ({', '.join(values)}); using {num}/{den} "
            "for the whole song (changing meter is supported in a later release)",
        )

    tracks: list[Track] = []
    used_ids: dict[str, int] = {}
    unmapped: dict[int, int] = defaultdict(int)
    channels_per_track: dict[int, int] = defaultdict(int)
    for t_index, _ in notes:
        channels_per_track[t_index] += 1

    for (t_index, channel) in sorted(notes):
        raw = sorted(notes[(t_index, channel)])
        if not raw:
            continue
        name = names.get(t_index, "")
        program = programs.get((t_index, channel))
        if channel == DRUM_CHANNEL:
            role = "drums"
            events = []
            for start, _end, pitch, velocity in raw:
                drum = GM_DRUMS.get(pitch)
                if drum is None:
                    unmapped[pitch] += 1
                    continue
                events.append(Hit(beats(start), drum, velocity))
            instrument = "gm:drums"
        else:
            role = guess_role(name, program, raw)
            events = [
                Note(beats(start), beats(max(end - start, 1)), pitch, velocity)
                for start, end, pitch, velocity in raw
            ]
            instrument = f"gm:{program}" if program is not None else None
        if not events:
            continue
        base = slug(name) or role
        if channels_per_track[t_index] > 1 and slug(name):
            base = f"{base}_ch{channel + 1}"
        count = used_ids.get(base, 0) + 1
        used_ids[base] = count
        track_id = base if count == 1 else f"{base}_{count}"
        tracks.append(Track(events=tuple(events), id=track_id, role=role, instrument=instrument))

    if unmapped:
        detail = ", ".join(f"{p} x{n}" for p, n in sorted(unmapped.items()))
        warn(STAGE, f"dropped drum notes with no IR drum name (GM key x count): {detail}")

    title = None
    if 0 in names and not any(t == 0 for t, _ in notes):
        title = names[0] or None

    return Song(
        meta=Meta(
            title=title or path.stem,
            bpm=bpm_value,
            time_signature=(num, den),
            key=keys[0][1] if keys else None,
            source=path.name,
            pickup_beats=pickup,
        ),
        tracks=tuple(tracks),
    )

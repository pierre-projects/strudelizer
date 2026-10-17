"""Guitar Pro importer (FR-12): .gp3, .gp4, .gp5 via PyGuitarPro.

Optional extra: `pip install "strudelizer[guitarpro]"`. PyGuitarPro is
imported only when a file is loaded, so the registry can check for it
cheaply (see Importer.requires).

- Every track becomes an IR track. Pitch = open string + fret + capo (the
  track's capo, `track.offset`). Percussion tracks map GM keys to drums.
- Repeats and alternate endings are unfolded into one linear song;
  measure markers become sections, in played order.
- Tempo and meter come from the file; changes follow Decision 4's rule
  (the value in force longest wins) with a warning.
- Techniques are ignored, except: tied notes extend the note before them
  on the same string, dead notes and grace notes are dropped.
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.gm import GM_DRUMS, guess_role, slug, unique_ids
from ..core.ir import Hit, Meta, Note, Section, Song, Track
from ..core.theory import format_key
from ..core.time import dominant
from ..registry import Importer

STAGE = "import:guitarpro"
QUARTER = 960  # PyGuitarPro ticks per quarter note
MAX_UNFOLDED = 10_000


def unfold(headers: list[Any]) -> list[int]:
    """Measure indexes in playing order: repeats are taken (repeatClose =
    number of jumps back) and alternate endings are played only on the
    passes in their bitmask."""
    order: list[int] = []
    jumps: dict[int, int] = defaultdict(int)
    i, start, passes, returning_to = 0, 0, 1, None
    while i < len(headers):
        if len(order) > MAX_UNFOLDED:
            raise StrudelizerError(STAGE, "the repeats never end", location=f"measure {i + 1}",
                                   fix="check the repeat signs in the file")
        header = headers[i]
        if header.isRepeatOpen and returning_to != i:
            start, passes = i, 1
        returning_to = None
        endings = header.repeatAlternative
        if endings and not (endings >> (passes - 1)) & 1:
            i += 1
            continue
        order.append(i)
        if header.repeatClose > 0:
            if jumps[i] < header.repeatClose:
                jumps[i] += 1
                passes += 1
                returning_to = start
                i = start
                continue
            jumps[i] = 0  # an outer repeat may play this one again
        i += 1
    return order


def _key_name(signature: Any) -> str | None:
    try:
        sharps, minor = signature.value
    except (AttributeError, TypeError, ValueError):
        return None
    major = (sharps * 7) % 12
    return format_key((major + 9) % 12 if minor else major, bool(minor))


def _quarters(ticks: int) -> Fraction:
    return Fraction(ticks, QUARTER)


class GuitarProImporter(Importer):
    """Guitar Pro 3-5 tabs (.gp3, .gp4, .gp5); needs the guitarpro extra."""

    name = "guitarpro"
    extensions = (".gp3", ".gp4", ".gp5")
    requires = ("guitarpro",)

    def load(self, path: str | Path, options: Mapping[str, Any]) -> Song:
        import guitarpro

        path = Path(path)
        if not path.exists():
            raise StrudelizerError(STAGE, "file not found", location=str(path))
        try:
            gp_song = guitarpro.parse(str(path))
        except Exception as exc:  # PyGuitarPro raises many kinds of errors on bad files
            raise StrudelizerError(
                STAGE, f"not a readable Guitar Pro file ({exc})", location=str(path),
                fix="save it from Guitar Pro or TuxGuitar as .gp5 (versions 3 to 5 are supported)",
            ) from None
        return _convert(gp_song, path, options)


def _convert(gp_song: Any, path: Path, options: Mapping[str, Any]) -> Song:
    headers = gp_song.measureHeaders
    order = unfold(headers)

    # unfolded measure start times, in quarter notes
    starts: list[Fraction] = []
    time = Fraction(0)
    for index in order:
        starts.append(time)
        sig = headers[index].timeSignature
        time += Fraction(sig.numerator * 4, sig.denominator.value)
    end = time

    meters = [(starts[k], (headers[i].timeSignature.numerator, headers[i].timeSignature.denominator.value))
              for k, i in enumerate(order)]
    tempos = [(Fraction(0), gp_song.tempo)]
    for track in gp_song.tracks:
        for k, i in enumerate(order):
            measure = track.measures[i]
            for voice in measure.voices:
                for beat in voice.beats:
                    change = getattr(beat.effect, "mixTableChange", None)
                    if change is not None and change.tempo is not None and change.tempo.value > 0:
                        tempos.append((starts[k] + _quarters(beat.start - measure.start), change.tempo.value))
    qbpm, tempo_changed = dominant(tempos, 120, end)
    (num, den), meter_changed = dominant(meters, (4, 4), end)
    if tempo_changed:
        values = sorted({v for _, v in tempos})
        warn(STAGE, f"tempo changes found ({', '.join(map(str, values))} bpm); using the dominant tempo "
                    f"{qbpm} for the whole song (tempo changes are supported in a later release)")
    if meter_changed:
        values = sorted({f"{n}/{d}" for _, (n, d) in meters})
        warn(STAGE, f"time signature changes found ({', '.join(values)}); using {num}/{den} for the whole "
                    "song (changing meter is supported in a later release)")
    scale = Fraction(den, 4)  # quarter notes -> IR beats

    tracks: list[tuple[str, Track]] = []
    dropped: dict[str, int] = defaultdict(int)
    for track in gp_song.tracks:
        percussion = track.isPercussionTrack or track.channel.channel == 9
        capo = 0 if percussion else track.offset
        notes: list[list] = []  # [start, end, pitch, velocity] in quarter notes, mutable for ties
        hits: list[Hit] = []
        open_by_string: dict[tuple[int, int], int] = {}  # (voice, string) -> index in notes
        for k, i in enumerate(order):
            measure = track.measures[i]
            for v, voice in enumerate(measure.voices):
                for beat in voice.beats:
                    if beat.status != beat.status.normal:
                        continue
                    start = starts[k] + _quarters(beat.start - measure.start)
                    length = _quarters(beat.duration.time)
                    for note in beat.notes:
                        kind = note.type.name
                        if kind == "rest":
                            continue
                        if kind == "dead":
                            dropped["dead notes"] += 1
                            continue
                        if note.effect.isGrace:
                            # GP stores a grace note as an effect on the main
                            # note; the ornament is dropped, the note is kept.
                            dropped["grace notes"] += 1
                        velocity = max(1, min(127, int(note.velocity)))
                        if percussion:
                            if kind == "tie":
                                continue
                            drum = GM_DRUMS.get(note.value)
                            if drum is None:
                                dropped[f"unmapped drum key {note.value}"] += 1
                                continue
                            hits.append(Hit(start * scale, drum, velocity))
                            continue
                        key = (v, note.string)
                        if kind == "tie" and key in open_by_string:
                            notes[open_by_string[key]][1] = start + length  # extend the tied note
                            continue
                        pitch = track.strings[note.string - 1].value + note.value + capo
                        if not 0 <= pitch <= 127:
                            dropped["notes outside the MIDI range"] += 1
                            continue
                        open_by_string[key] = len(notes)
                        notes.append([start, start + length, pitch, velocity])
        if percussion:
            if hits:
                tracks.append((slug(track.name) or "drums", Track(events=tuple(hits), role="drums",
                                                                   instrument="gm:drums")))
            continue
        if not notes:
            continue
        program = track.channel.instrument
        name = track.name or ""
        role = guess_role(name, program, [tuple(n) for n in notes])
        if len(track.strings) in (4, 5) and role != "bass" and min(s.value for s in track.strings) < 40:
            role = "bass"
        events = tuple(Note(s * scale, (e - s) * scale, p, vel) for s, e, p, vel in notes)
        tracks.append((slug(name) or role, Track(events=events, role=role, instrument=f"gm:{program}")))

    if dropped:
        detail = ", ".join(f"{n} {what}" for what, n in sorted(dropped.items()))
        warn(STAGE, f"left out: {detail}")

    ids = unique_ids([base for base, _ in tracks])
    out_tracks = tuple(Track(events=t.events, id=i, role=t.role, instrument=t.instrument)
                       for i, (_, t) in zip(ids, tracks))

    # markers become sections, in played order
    sections = []
    marks = [(k, headers[i].marker.title) for k, i in enumerate(order) if headers[i].marker is not None]
    for n, (k, title) in enumerate(marks):
        stop = marks[n + 1][0] if n + 1 < len(marks) else len(order)
        if stop > k:
            sections.append(Section(start_bar=k, length=stop - k, name=slug(title) or "section"))
    if meter_changed:
        sections = []  # bar indexes would not line up with a single meter

    bpm = round(qbpm * den / 4, 3)
    return Song(
        meta=Meta(
            title=gp_song.title or path.stem,
            bpm=int(bpm) if bpm == int(bpm) else bpm,
            time_signature=(num, den),
            key=_key_name(headers[0].keySignature) if headers else None,
            source=path.name,
        ),
        sections=tuple(sections),
        tracks=out_tracks,
    )

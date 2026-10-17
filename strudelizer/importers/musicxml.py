"""MusicXML importer (FR-14): .musicxml, .xml and compressed .mxl via music21.

Optional extra: `pip install "strudelizer[musicxml]"`. music21 is imported
only when a file is loaded (see Importer.requires).

- Each part becomes a track (unpitched percussion parts become drum hits
  when their instrument names a GM key); rests and grace notes are left out.
- Repeats and endings are unfolded (music21 expandRepeats) and tied notes
  are merged into one long note (stripTies).
- Harmony symbols become chord events on a `chords` track, parsed with
  core.theory.parse_chord; each lasts until the next symbol.
- Tempo and meter changes follow Decision 4's rule with a warning; an
  implicit first measure shorter than the bar is a pickup.
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import StrudelizerError, warn
from ..core.gm import GM_DRUMS, guess_role, slug, unique_ids
from ..core.ir import Chord, Hit, Meta, Note, Song, Track
from ..core.theory import format_key, parse_chord, pitch_class
from ..core.time import dominant
from ..registry import Importer

STAGE = "import:musicxml"

# music21 / MusicXML chord kind -> spelling after the root (core.theory grammar)
KIND_SPELLING = {
    "major": "", "minor": "m", "augmented": "aug", "diminished": "dim",
    "dominant": "7", "dominant-seventh": "7", "major-seventh": "maj7",
    "minor-major-seventh": "mmaj7", "minor-seventh": "m7",
    "half-diminished": "m7b5", "half-diminished-seventh": "m7b5",
    "diminished-seventh": "dim7", "major-sixth": "6", "minor-sixth": "m6",
    "major-ninth": "maj9", "dominant-ninth": "9", "minor-ninth": "m9",
    "dominant-11th": "11", "dominant-13th": "13",
    "suspended-second": "sus2", "suspended-fourth": "sus4",
    "suspended-fourth-seventh": "7sus4", "power": "5",
}


def _frac(value: Any) -> Fraction:
    """music21 offsets are floats (exact for halves, quarters...) or Fractions."""
    return Fraction(value).limit_denominator(1 << 16)


def _note_name(name: str) -> str:
    """music21 spells flats with '-': 'B-' -> 'Bb'."""
    return name.replace("-", "b")


class MusicXmlImporter(Importer):
    """MusicXML scores (.musicxml, .xml, .mxl); needs the musicxml extra."""

    name = "musicxml"
    extensions = (".musicxml", ".mxl", ".xml")
    requires = ("music21",)

    def can_handle(self, path: str | Path) -> bool:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in (".musicxml", ".mxl"):
            return True
        if suffix == ".xml":
            try:
                head = path.read_bytes()[:2000]
            except OSError:
                return False
            return b"score-partwise" in head or b"score-timewise" in head
        return False

    def load(self, path: str | Path, options: Mapping[str, Any]) -> Song:
        from music21 import converter

        path = Path(path)
        if not path.exists():
            raise StrudelizerError(STAGE, "file not found", location=str(path))
        try:
            score = converter.parse(str(path))
        except Exception as exc:  # music21 raises many kinds of errors on bad files
            raise StrudelizerError(
                STAGE, f"not a readable MusicXML file ({exc})", location=str(path),
                fix="export the score as MusicXML (.musicxml or .mxl) from your notation program",
            ) from None
        return _convert(score, path, options)


def _convert(score: Any, path: Path, options: Mapping[str, Any]) -> Song:
    from music21 import harmony, key as m21key, meter, note, chord

    try:
        expanded = score.expandRepeats()
    except Exception as exc:  # malformed repeats: read the score as written
        warn(STAGE, f"could not unfold the repeats ({exc}); read the score as written")
        expanded = score
    parts = list(expanded.parts) if hasattr(expanded, "parts") and expanded.parts else [expanded]
    end = _frac(expanded.highestTime)

    first = parts[0].flatten()
    meters = [(_frac(ts.offset), (ts.numerator, ts.denominator)) for ts in first.getElementsByClass(meter.TimeSignature)]
    (num, den), meter_changed = dominant(meters, (4, 4), end)
    tempos = []
    try:
        for start, _stop, mark in expanded.metronomeMarkBoundaries():
            bpm = mark.getQuarterBPM()
            if bpm:
                tempos.append((_frac(start), round(float(bpm), 3)))
    except Exception:
        pass
    qbpm, tempo_changed = dominant(tempos, 120.0, end)
    if tempo_changed:
        values = sorted({v for _, v in tempos})
        warn(STAGE, f"tempo changes found ({', '.join(f'{v:g}' for v in values)} bpm); using the dominant "
                    f"tempo {qbpm:g} for the whole song (tempo changes are supported in a later release)")
    if meter_changed:
        values = sorted({f"{n}/{d}" for _, (n, d) in meters})
        warn(STAGE, f"time signature changes found ({', '.join(values)}); using {num}/{den} for the whole "
                    "song (changing meter is supported in a later release)")
    scale = Fraction(den, 4)  # quarter notes -> IR beats

    # pickup: an implicit first measure shorter than the bar
    pickup = None
    measures = parts[0].getElementsByClass("Measure")
    if measures and getattr(measures[0], "paddingLeft", 0):
        bar = _frac(measures[0].barDuration.quarterLength)
        length = bar - _frac(measures[0].paddingLeft)
        if 0 < length < bar:
            pickup = length * scale

    key_name = None
    for ks in first.getElementsByClass(m21key.KeySignature):
        k = ks if isinstance(ks, m21key.Key) else ks.asKey()
        key_name = format_key(pitch_class(_note_name(k.tonic.name)), k.mode == "minor")
        break

    dropped: dict[str, int] = defaultdict(int)
    tracks: list[tuple[str, Track]] = []
    symbols: dict[Fraction, Any] = {}
    for part in parts:
        flat = part.stripTies().flatten()
        name = part.partName or ""
        instrument = part.getInstrument(returnDefault=False)
        program = getattr(instrument, "midiProgram", None) if instrument is not None else None
        notes: list[tuple[Fraction, Fraction, int, int | None]] = []
        hits: list[Hit] = []
        for element in flat.notesAndRests:
            if isinstance(element, harmony.ChordSymbol):
                symbols.setdefault(_frac(element.offset), element)
                continue
            if element.isRest:
                continue
            if element.duration.isGrace:
                dropped["grace notes"] += 1
                continue
            start = _frac(element.offset)
            length = _frac(element.quarterLength)
            velocity = element.volume.velocity if element.volume.velocity is not None else None
            if isinstance(element, note.Unpitched):
                gm = getattr(getattr(element, "storedInstrument", None), "percMapPitch", None)
                drum = GM_DRUMS.get(gm) if gm is not None else None
                if drum is None:
                    dropped["unpitched notes without a GM drum"] += 1
                    continue
                hits.append(Hit(start * scale, drum, velocity))
                continue
            if isinstance(element, chord.Chord):
                pitches = [p.midi for p in element.pitches]
            elif isinstance(element, note.Note):
                pitches = [element.pitch.midi]
            else:
                continue
            for pitch in pitches:
                notes.append((start, start + length, pitch, int(velocity) if velocity else None))
        if hits:
            tracks.append((slug(name) or "drums", Track(events=tuple(hits), role="drums", instrument="gm:drums")))
        if notes:
            role = guess_role(name, program, notes)
            events = tuple(Note(s * scale, (e - s) * scale, p, v) for s, e, p, v in notes if e > s)
            tracks.append((slug(name) or role, Track(events=events, role=role,
                                                     instrument=f"gm:{program}" if program is not None else None)))

    chords = _chord_events(symbols, end, scale, dropped)
    if chords:
        tracks.insert(0, ("chords", Track(events=tuple(chords), role="chords")))
    if dropped:
        detail = ", ".join(f"{n} {what}" for what, n in sorted(dropped.items()))
        warn(STAGE, f"left out: {detail}")
    if not tracks:
        raise StrudelizerError(STAGE, "the score has no notes or chord symbols", location=str(path))

    ids = unique_ids([base for base, _ in tracks])
    title = None
    if score.metadata is not None:
        title = score.metadata.title or score.metadata.movementName
    bpm = round(qbpm * den / 4, 3)
    return Song(
        meta=Meta(
            title=title or path.stem,
            bpm=int(bpm) if bpm == int(bpm) else bpm,
            time_signature=(num, den),
            key=key_name,
            source=path.name,
            pickup_beats=pickup,
        ),
        tracks=tuple(Track(events=t.events, id=i, role=t.role, instrument=t.instrument)
                     for i, (_, t) in zip(ids, tracks)),
    )


def _chord_events(symbols: dict[Fraction, Any], end: Fraction, scale: Fraction, dropped: dict[str, int]) -> list[Chord]:
    """Chord symbols, each lasting until the next one (or the end)."""
    out = []
    starts = sorted(symbols)
    for i, start in enumerate(starts):
        cs = symbols[start]
        stop = starts[i + 1] if i + 1 < len(starts) else end
        if stop <= start:
            continue
        symbol = _symbol(cs)
        spelling = parse_chord(symbol) if symbol else None
        if spelling is None:
            pitches = tuple(sorted(p.midi for p in cs.pitches)) if cs.pitches else None
            if not pitches:
                dropped[f"chord symbols with an unknown kind ({cs.chordKind})"] += 1
                continue
            out.append(Chord(start * scale, (stop - start) * scale, _note_name(cs.figure), pitches=pitches))
            continue
        out.append(
            Chord(
                start * scale,
                (stop - start) * scale,
                symbol,
                root=spelling.root,
                quality=spelling.quality,
                extensions=spelling.extensions or None,
                bass=spelling.bass,
                pitches=spelling.pitches(),
            )
        )
    return out


def _symbol(cs: Any) -> str | None:
    """A ChordSymbol as text the core chord grammar reads, e.g. 'F/A'."""
    suffix = KIND_SPELLING.get(cs.chordKind)
    root = cs.root()
    if suffix is None or root is None:
        return None
    symbol = _note_name(root.name) + suffix
    bass = cs.bass()
    if bass is not None and bass.name != root.name:
        symbol += "/" + _note_name(bass.name)
    return symbol

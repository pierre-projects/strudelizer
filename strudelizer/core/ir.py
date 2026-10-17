"""The Song IR (FR-1 to FR-6): the only contract between stages.

Python objects are frozen dataclasses so passes cannot mutate their input.
Times are `fractions.Fraction` in beats; JSON stores them as "n/d" strings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from importlib import resources
from typing import Any, Iterable, Mapping, Union

from .errors import StrudelizerError
from .time import format_frac, parse_frac

IR_VERSION = "2"
SUPPORTED_VERSIONS = ("1", "2")  # older versions are migrated on load

ROLES = ("drums", "bass", "chords", "melody", "vocal", "other")

# Decision 3: the IR's own drum vocabulary, in canonical order.
# IR v2 added cowbell, tambourine and shaker (appended, so the order of the
# original eleven is unchanged).
DRUMS = (
    "kick",
    "snare",
    "closed_hat",
    "open_hat",
    "clap",
    "rim",
    "tom_low",
    "tom_mid",
    "tom_high",
    "crash",
    "ride",
    "cowbell",
    "tambourine",
    "shaker",
)


@dataclass(frozen=True)
class Note:
    start: Fraction
    duration: Fraction
    pitch: int
    velocity: int | None = None
    type: str = field(default="note", init=False, repr=False)


@dataclass(frozen=True)
class Hit:
    start: Fraction
    drum: str
    velocity: int | None = None
    type: str = field(default="hit", init=False, repr=False)


@dataclass(frozen=True)
class Chord:
    start: Fraction
    duration: Fraction
    symbol: str
    root: str | None = None
    quality: str | None = None
    extensions: tuple[str, ...] | None = None
    bass: str | None = None
    pitches: tuple[int, ...] | None = None
    type: str = field(default="chord", init=False, repr=False)


Event = Union[Note, Hit, Chord]

_TYPE_ORDER = {"hit": 0, "note": 1, "chord": 2}


def event_sort_key(event: Event) -> tuple:
    if isinstance(event, Hit):
        detail: tuple = (DRUMS.index(event.drum), Fraction(0))
    elif isinstance(event, Note):
        detail = (event.pitch, event.duration)
    else:
        detail = (event.symbol, event.duration)
    return (event.start, _TYPE_ORDER[event.type], *detail, getattr(event, "velocity", None) or 0)


def sort_events(events: Iterable[Event]) -> list[Event]:
    return sorted(events, key=event_sort_key)


@dataclass(frozen=True)
class Meta:
    title: str | None = None
    bpm: float | None = None
    time_signature: tuple[int, int] | None = None
    key: str | None = None
    source: str | None = None
    # Length of a partial first bar (anacrusis), in beats. Event times still
    # start at 0 = the start of the pickup; bar 1 starts at `pickup_beats`.
    pickup_beats: Fraction | None = None


@dataclass(frozen=True)
class Section:
    start_bar: int
    length: int
    name: str | None = None


@dataclass(frozen=True)
class Track:
    events: tuple[Event, ...]
    id: str | None = None
    role: str | None = None
    instrument: str | None = None
    bars: tuple[int, ...] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(sort_events(self.events)))
        if self.bars is not None:
            object.__setattr__(self, "bars", tuple(self.bars))


@dataclass(frozen=True)
class Song:
    tracks: tuple[Track, ...]
    meta: Meta = field(default_factory=Meta)
    sections: tuple[Section, ...] = ()
    version: str = IR_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tracks", tuple(self.tracks))
        object.__setattr__(self, "sections", tuple(self.sections))

    # ---- serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": self.version, "meta": _meta_to_dict(self.meta)}
        out["sections"] = [_section_to_dict(s) for s in self.sections]
        out["tracks"] = [_track_to_dict(t) for t in self.tracks]
        for key in sorted(self.extra):
            out[key] = self.extra[key]
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], stage: str = "ir", validate: bool = True) -> "Song":
        data = migrate(data, stage)
        if validate:
            validate_dict(data, stage)
        meta = data.get("meta", {})
        ts = meta.get("time_signature")
        pickup = meta.get("pickup_beats")
        return cls(
            version=IR_VERSION,
            meta=Meta(
                title=meta.get("title"),
                bpm=meta.get("bpm"),
                time_signature=(ts[0], ts[1]) if ts else None,
                key=meta.get("key"),
                source=meta.get("source"),
                pickup_beats=parse_frac(pickup) if pickup is not None else None,
            ),
            sections=tuple(
                Section(start_bar=s["start_bar"], length=s["length"], name=s.get("name"))
                for s in data.get("sections", [])
            ),
            tracks=tuple(_track_from_dict(t) for t in data["tracks"]),
            extra={k: v for k, v in data.items() if k.startswith("x-")},
        )

    @classmethod
    def from_json(cls, text: str, stage: str = "ir", location: str | None = None) -> "Song":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrudelizerError(
                stage,
                f"not valid JSON: {exc.msg}",
                location=f"{location or 'input'} line {exc.lineno}, column {exc.colno}",
                fix="check the file is a Song IR JSON document written by `strudelize import`",
            ) from None
        return cls.from_dict(data, stage=stage)

    def validate(self, stage: str = "ir") -> "Song":
        validate_dict(self.to_dict(), stage)
        return self


# ---- dict conversion helpers ---------------------------------------------


def _drop_none(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    return {k: v for k, v in pairs if v is not None}


def _meta_to_dict(meta: Meta) -> dict[str, Any]:
    return _drop_none(
        [
            ("title", meta.title),
            ("bpm", meta.bpm),
            ("time_signature", list(meta.time_signature) if meta.time_signature else None),
            ("key", meta.key),
            ("source", meta.source),
            ("pickup_beats", format_frac(meta.pickup_beats) if meta.pickup_beats is not None else None),
        ]
    )


def migrate(data: Mapping[str, Any], stage: str = "ir") -> Mapping[str, Any]:
    """Bring an older IR document up to IR_VERSION.

    v1 -> v2 adds only optional things (meta.pickup_beats and three drum
    names), so every v1 document is a valid v2 document once relabelled.
    """
    if not isinstance(data, Mapping):
        return data  # let schema validation report it
    version = data.get("version", IR_VERSION)
    if version == IR_VERSION:
        return data
    if version not in SUPPORTED_VERSIONS:
        raise StrudelizerError(
            stage,
            f"unsupported IR version {version!r} (this Strudelizer reads {', '.join(SUPPORTED_VERSIONS)})",
            location="version",
            fix="upgrade Strudelizer, or write the IR with a matching version",
        )
    return {**data, "version": IR_VERSION}


def _section_to_dict(section: Section) -> dict[str, Any]:
    return _drop_none(
        [("name", section.name), ("start_bar", section.start_bar), ("length", section.length)]
    )


def _track_to_dict(track: Track) -> dict[str, Any]:
    out = _drop_none(
        [
            ("id", track.id),
            ("role", track.role),
            ("instrument", track.instrument),
            ("bars", list(track.bars) if track.bars is not None else None),
        ]
    )
    out["events"] = [event_to_dict(e) for e in track.events]
    for key in sorted(track.extra):
        out[key] = track.extra[key]
    return out


def event_to_dict(event: Event) -> dict[str, Any]:
    if isinstance(event, Note):
        return _drop_none(
            [
                ("type", "note"),
                ("start", format_frac(event.start)),
                ("duration", format_frac(event.duration)),
                ("pitch", event.pitch),
                ("velocity", event.velocity),
            ]
        )
    if isinstance(event, Hit):
        return _drop_none(
            [
                ("type", "hit"),
                ("start", format_frac(event.start)),
                ("drum", event.drum),
                ("velocity", event.velocity),
            ]
        )
    return _drop_none(
        [
            ("type", "chord"),
            ("start", format_frac(event.start)),
            ("duration", format_frac(event.duration)),
            ("symbol", event.symbol),
            ("root", event.root),
            ("quality", event.quality),
            ("extensions", list(event.extensions) if event.extensions is not None else None),
            ("bass", event.bass),
            ("pitches", list(event.pitches) if event.pitches is not None else None),
        ]
    )


def event_from_dict(data: Mapping[str, Any]) -> Event:
    kind = data["type"]
    start = parse_frac(data["start"])
    if kind == "note":
        return Note(start, parse_frac(data["duration"]), data["pitch"], data.get("velocity"))
    if kind == "hit":
        return Hit(start, data["drum"], data.get("velocity"))
    return Chord(
        start,
        parse_frac(data["duration"]),
        data["symbol"],
        root=data.get("root"),
        quality=data.get("quality"),
        extensions=tuple(data["extensions"]) if "extensions" in data else None,
        bass=data.get("bass"),
        pitches=tuple(data["pitches"]) if "pitches" in data else None,
    )


def _track_from_dict(data: Mapping[str, Any]) -> Track:
    return Track(
        events=tuple(event_from_dict(e) for e in data["events"]),
        id=data.get("id"),
        role=data.get("role"),
        instrument=data.get("instrument"),
        bars=tuple(data["bars"]) if "bars" in data else None,
        extra={k: v for k, v in data.items() if k.startswith("x-")},
    )


# ---- schema validation (FR-5) ----------------------------------------------


def load_schema() -> dict[str, Any]:
    return json.loads(_schema_text())


@lru_cache(maxsize=1)
def _schema_text() -> str:
    return resources.files("strudelizer.core").joinpath("schema.json").read_text(encoding="utf-8")


def _inline_refs(node: Any, defs: Mapping[str, Any]) -> Any:
    """Replace local {"$ref": "#/$defs/x"} with the definition itself.

    The schema has no recursive definitions, so this terminates; it gives
    the same verdicts and roughly a third faster validation (no reference
    lookups per event).
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = _inline_refs(defs[ref[len("#/$defs/"):]], defs)
            siblings = {k: _inline_refs(v, defs) for k, v in node.items() if k != "$ref"}
            # 2020-12 applies a $ref alongside its siblings; annotations
            # such as "description" are the only siblings used here.
            return {**target, **siblings}
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator

    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(_inline_refs(schema, schema.get("$defs", {})))


def _json_path(path: Iterable[Any]) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "(document root)"


def validate_dict(data: Any, stage: str = "ir") -> None:
    """Raise StrudelizerError naming the first schema violation, if any."""
    from jsonschema.exceptions import best_match

    validator = _validator()
    if not validator.is_valid(data):
        error = best_match(validator.iter_errors(data))
        raise StrudelizerError(
            stage,
            f"Song IR does not match the schema: {error.message}",
            location=_json_path(error.absolute_path),
            fix="see strudelizer/core/schema.json for the IR format",
        )
    # Rules JSON Schema cannot express.
    meta = data.get("meta", {})
    if "pickup_beats" in meta:
        bar = meta.get("time_signature", [4, 4])[0]
        if parse_frac(meta["pickup_beats"]) >= bar:
            raise StrudelizerError(
                stage,
                f"pickup_beats {meta['pickup_beats']} is not shorter than a bar ({bar} beats)",
                location="meta.pickup_beats",
                fix="a pickup is a partial first bar; drop the field for a full first bar",
            )

"""Core contract: the Song IR, its schema, and time/theory helpers."""

from .errors import StrudelizerError, StrudelizerWarning
from .ir import DRUMS, ROLES, Chord, Event, Hit, Meta, Note, Section, Song, Track, validate_dict

__all__ = [
    "DRUMS",
    "ROLES",
    "Chord",
    "Event",
    "Hit",
    "Meta",
    "Note",
    "Section",
    "Song",
    "StrudelizerError",
    "StrudelizerWarning",
    "Track",
    "validate_dict",
]

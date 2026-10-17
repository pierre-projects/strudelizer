"""Strudelizer: convert music files into Strudel live-coding patterns."""

__version__ = "0.3.0"  # P1-P3; the package version is read from here

from .core import Song, StrudelizerError, StrudelizerWarning  # noqa: E402

__all__ = ["Pipeline", "Song", "StrudelizerError", "StrudelizerWarning", "__version__"]


def __getattr__(name: str):
    # Imported lazily so `import strudelizer` stays cheap and cycle-free.
    if name == "Pipeline":
        from .pipeline import Pipeline

        return Pipeline
    raise AttributeError(name)

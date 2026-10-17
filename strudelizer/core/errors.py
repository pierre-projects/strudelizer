"""Errors and warnings shared by every stage (FR-44).

Every error names the stage that raised it, where in the input the problem is
(bar, track, line, file, or JSON path), and the fix when one is known.
"""

from __future__ import annotations

import warnings


class StrudelizerError(Exception):
    """A user-facing failure in one pipeline stage."""

    def __init__(
        self,
        stage: str,
        message: str,
        location: str | None = None,
        fix: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.location = location
        self.fix = fix

    def __str__(self) -> str:
        where = f" at {self.location}" if self.location else ""
        text = f"[{self.stage}]{where}: {self.message}"
        if self.fix:
            text += f"\n  fix: {self.fix}"
        return text


class StrudelizerWarning(UserWarning):
    """A recoverable problem: the stage continued with a documented fallback."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(stage, message)
        self.stage = stage
        self.message = message

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}"


def warn(stage: str, message: str) -> None:
    warnings.warn(StrudelizerWarning(stage, message), stacklevel=3)

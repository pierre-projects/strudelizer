"""Errors and warnings as JSON, worded exactly like the CLI (FR-44).

The pipeline reports problems in two ways: `StrudelizerError` for failures and
`StrudelizerWarning` (through `warnings.warn`) for a stage that continued with a
documented fallback. Both carry a stage; errors also carry a location and a fix.
"""

from __future__ import annotations

import re
import warnings
from contextlib import contextmanager
from typing import Any, Iterator

from strudelizer.core.errors import StrudelizerError, StrudelizerWarning

# Importers put the source line in the message itself ("line 16: skipped ...").
_LINE = re.compile(r"\bline (\d+)\b")
# Emitters and passes name a bar ("at bar 7", "the pickup bar").
_BAR = re.compile(r"\bbar (\d+)\b")


def error_payload(exc: StrudelizerError) -> dict[str, Any]:
    """The CLI's `error [stage] at <location>: <message>` as fields plus text."""
    where = f" at {exc.location}" if exc.location else ""
    text = f"error [{exc.stage}]{where}: {exc.message}"
    if exc.fix:
        text += f"\n  fix: {exc.fix}"
    return {
        "stage": exc.stage,
        "message": exc.message,
        "location": exc.location,
        "fix": exc.fix,
        "text": text,
        **_where(f"{exc.location or ''} {exc.message}"),
    }


def warning_payload(warning: StrudelizerWarning) -> dict[str, Any]:
    """The CLI's `warning [stage]: <message>` as fields, with the line it names."""
    return {
        "stage": warning.stage,
        "message": warning.message,
        "text": f"warning [{warning.stage}]: {warning.message}",
        **_where(warning.message),
    }


def _where(text: str) -> dict[str, int]:
    """Pull a source line or bar number out of the message, for the Problems panel."""
    out = {}
    line = _LINE.search(text)
    if line:
        out["line"] = int(line.group(1))
    bar = _BAR.search(text)
    if bar:
        out["bar"] = int(bar.group(1))
    return out


@contextmanager
def collect_warnings() -> Iterator[list[dict[str, Any]]]:
    """Collect this stage's StrudelizerWarnings into the yielded list.

    `warnings.catch_warnings` swaps a process-global filter list, so every
    endpoint that uses this must run in one thread; see `routes.py`.
    """
    collected: list[dict[str, Any]] = []
    with warnings.catch_warnings(record=True) as caught:
        # "always": the warning registry would otherwise swallow a repeat of a
        # message the user has already seen once this session.
        warnings.simplefilter("always", StrudelizerWarning)
        try:
            yield collected
        finally:
            collected.extend(
                warning_payload(w.message)
                for w in caught
                if isinstance(w.message, StrudelizerWarning)
            )

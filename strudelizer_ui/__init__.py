"""Local web UI for Strudelizer: `strudelize ui` (install with `pip install -e ".[ui]"`).

The UI is a thin layer over the public Python API (`Pipeline`, the registry and
the Song IR). It adds no music logic of its own, so anything it can do is also
reachable from the CLI.

This module imports no web dependency, so `strudelize ui` can tell the
difference between "the extra is not installed" and "the UI is broken".
"""

from strudelizer import __version__

__all__ = ["__version__"]

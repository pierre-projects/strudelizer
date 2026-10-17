"""`python -m strudelizer_ui`, the same thing as `strudelize ui`."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from strudelizer.core.errors import StrudelizerError

from .server import DEFAULT_HOST, DEFAULT_PORT, serve


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m strudelizer_ui", description="Strudelizer web UI.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"address to listen on (default {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args(argv)
    try:
        serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    except StrudelizerError as exc:
        print(f"error {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

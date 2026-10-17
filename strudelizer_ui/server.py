"""Start the local server and open a browser: the body of `strudelize ui`."""

from __future__ import annotations

import socket
import threading
import webbrowser

from strudelizer.core.errors import StrudelizerError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> None:
    import uvicorn

    from .app import create_app

    _check_free(host, port)
    url = f"http://{host}:{port}/"
    print(f"Strudelizer UI on {url}  (ctrl+c to stop)", flush=True)
    if open_browser:
        # The server is not listening yet; give it a moment rather than racing it.
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


def _check_free(host: str, port: int) -> None:
    """Fail with a fix rather than uvicorn's traceback when the port is taken."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((host, port)) == 0:
            raise StrudelizerError(
                "ui",
                f"something is already listening on {host}:{port}",
                fix="stop it, or run `strudelize ui --port 8766`",
            )

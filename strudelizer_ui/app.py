"""The FastAPI app: the API under /api, the built frontend on /.

Nothing here is reachable from outside the machine unless the user asks for it
(`strudelize ui --host`), and no file the user drops in is ever written anywhere
but a temporary directory that is deleted straight after the import.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from strudelizer import __version__
from strudelizer.core.errors import StrudelizerError

from .report import error_payload
from .routes import STAGE, router

STATIC = Path(__file__).parent / "static"

NO_FRONTEND = """<!doctype html>
<title>Strudelizer</title>
<body style="font:16px/1.6 system-ui;max-width:40em;margin:4em auto;padding:0 1em">
<h1>Strudelizer UI</h1>
<p>The API is running, but the frontend has not been built. From the repository:</p>
<pre style="background:#eee;padding:1em">npm install --prefix strudelizer_ui/frontend
npm run build --prefix strudelizer_ui/frontend</pre>
<p><a href="/api/plugins">/api/plugins</a> works either way.</p>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="Strudelizer UI", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.include_router(router, prefix="/api")

    @app.exception_handler(StrudelizerError)
    async def _pipeline_error(request: Request, exc: StrudelizerError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": error_payload(exc)})

    @app.exception_handler(RequestValidationError)
    async def _bad_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        error = StrudelizerError(
            STAGE,
            first.get("msg", "the request body is not valid"),
            location=where or None,
            fix="this is a bug in the UI; reload the page",
        )
        return JSONResponse(status_code=400, content={"error": error_payload(error)})

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        traceback.print_exc()
        error = StrudelizerError(
            STAGE,
            f"{type(exc).__name__}: {exc}",
            location=request.url.path,
            fix="this is a bug; the traceback is in the terminal running `strudelize ui`",
        )
        return JSONResponse(status_code=500, content={"error": error_payload(error)})

    if (STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    else:

        @app.get("/", include_in_schema=False)
        async def _placeholder() -> HTMLResponse:
            return HTMLResponse(NO_FRONTEND)

    return app

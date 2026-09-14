"""Serve the calibrator in a native window, wrapping the existing HTTP app.

This is an experiment in *chrome*, not in architecture. The React SPA still
talks HTTP to the FastAPI app ``create_app`` builds; pywebview is a WebView2
(on Windows) window pointed at that origin, instead of asking the user to
open a browser. A JS-bridge rewrite would be a second execution path, which
the calibrator is documented as deliberately not having.

``etsy-listings ui`` opens the window. ``--browser`` keeps the previous
behaviour: uvicorn in the foreground, URL printed, no GUI toolkit required.
That flag is also how the Vite dev loop and the playwright layer still work
-- both speak HTTP, and neither should have to drive a native window.

pywebview is imported only when a window is actually opened. Importing it at
module load would make every `ui --browser` run (and every test of one) depend
on a GUI backend that Ubuntu CI does not have.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastapi import FastAPI

from etsy_listings.errors import UserFacingError
from etsy_listings.ui.api.app import FRONTEND_DIST, create_app
from etsy_listings.workspace.workspace import Workspace

WINDOW_TITLE = "Mockup calibrator"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
WINDOW_MIN_SIZE = (1024, 700)
# Matches `--color-bg` so the window does not flash white before the SPA paints.
WINDOW_BACKGROUND = "#f5ead8"

_SERVER_START_TIMEOUT_SECONDS = 30


@dataclass
class RunningServer:
    """A uvicorn server on a daemon thread, already past ``started``."""

    host: str
    port: int
    _server: uvicorn.Server
    _thread: threading.Thread

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


def page_url(host: str, port: int) -> str:
    """The URL a window (or a browser) should open for this bind.

    ``0.0.0.0`` / ``::`` are listen addresses, not places WebView2 can
    navigate to -- the page is on loopback.
    """
    browse = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    return f"http://{browse}:{port}"


def start_server(app: FastAPI, host: str, port: int) -> RunningServer:
    """Bind ``app`` on a daemon thread and wait until it is accepting.

    The same shape the browser tests already use: ``uvicorn.run`` wants the
    main thread (signals), and so does pywebview (Windows STA / Cocoa), so
    the HTTP server is the one that yields.
    """
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="calibrator-http", daemon=True)
    thread.start()

    deadline = time.monotonic() + _SERVER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server.started:
            return RunningServer(host=host, port=port, _server=server, _thread=thread)
        if not thread.is_alive():
            raise UserFacingError(f"the calibrator server failed to start on {host}:{port}")
        time.sleep(0.05)

    server.should_exit = True
    thread.join(timeout=2)
    raise UserFacingError(f"the calibrator server did not start on {host}:{port} in time")


def _import_webview() -> Any:
    try:
        import webview
    except ImportError as exc:
        raise UserFacingError(
            "pywebview is not installed. Run `uv sync`, or pass --browser "
            "to serve the calibrator in a regular browser."
        ) from exc
    return webview


def open_window(url: str, *, debug: bool = False, webview: Any | None = None) -> None:
    """Block until the native window is closed.

    Must run on the main thread. ``webview`` is injectable so tests never
    import a GUI backend.
    """
    if webview is None:
        webview = _import_webview()
    try:
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
            background_color=WINDOW_BACKGROUND,
            text_select=True,
            zoomable=True,
            # Default is True, and the calibrator is a drag surface -- a box
            # drag must not steal the window.
            easy_drag=False,
        )
        webview.start(debug=debug)
    except UserFacingError:
        raise
    except Exception as exc:
        raise UserFacingError(
            f"could not open a native window ({exc}). "
            "Pass --browser to serve the calibrator in a regular browser."
        ) from exc


def run_calibrator(
    workspace: Workspace,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    browser: bool = False,
    debug: bool = False,
) -> None:
    """Serve the calibrator, in a native window unless ``browser`` is set.

    ``debug`` opens the web inspector on the native window and is ignored
    with ``--browser``.
    """
    app = create_app(workspace)
    if browser:
        uvicorn.run(app, host=host, port=port)
        return
    _serve_in_window(app, host=host, port=port, debug=debug)


def _serve_in_window(app: FastAPI, *, host: str, port: int, debug: bool) -> None:
    if not FRONTEND_DIST.is_dir():
        raise UserFacingError(
            "the calibrator frontend has not been built "
            "(src/etsy_listings/ui/frontend/dist is missing). "
            "Run `npm run build` in that directory, or pass --browser "
            "and use the Vite dev server on :5173."
        )
    server = start_server(app, host, port)
    url = page_url(host, port)
    sys.stdout.write(f"calibrator at {url}  (close the window to stop)\n")
    sys.stdout.flush()
    try:
        open_window(url, debug=debug)
    finally:
        server.stop()

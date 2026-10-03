"""Serves the calibrator the way `etsy-listings ui` does -- FastAPI hosting the
built SPA plus /api -- so the browser tests exercise the production shape, not
a Vite dev server that only exists on a developer's machine.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from etsy_listings.ui.api.app import FRONTEND_DIST, create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.server import stop_server

STARTUP_TIMEOUT_SECONDS = 30


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class _SingleProcessChromium:
    """Chromium in one process, for a sandbox that forbids its helpers.

    A sandbox that forbids Chromium's zygote and GPU helper processes (the
    macOS seatbelt agents run under) kills the normal launch with "Target
    page, context or browser has been closed". ``--single-process`` survives
    it, but in that mode a browser does not survive its contexts closing, so
    every ``new_context`` gets a browser of its own. Chromium does not support the
    mode, which is why it is only the fallback: CI, where the plain launch
    works, never builds one of these.
    """

    def __init__(self, chromium) -> None:  # noqa: ANN001
        self._chromium = chromium
        self._browser = chromium.launch(args=["--single-process"])

    def new_context(self, **kwargs):  # noqa: ANN003, ANN201
        # A fresh browser per context: one that has closed a context before is
        # not reliably able to open another in this mode.
        self.close()
        self._browser = self._chromium.launch(args=["--single-process"])
        return self._browser.new_context(**kwargs)

    def close(self) -> None:
        if self._browser.is_connected():
            self._browser.close()


def _launch(chromium):  # noqa: ANN001, ANN202 - playwright's types, as above
    try:
        return chromium.launch()
    except Exception:  # pragma: no cover - environment-dependent
        return _SingleProcessChromium(chromium)


@pytest.fixture(scope="session")
def browser_type(prerequisite_missing):  # noqa: ANN201 - playwright's type isn't worth importing at module scope
    try:
        from playwright import sync_api as playwright
    except ImportError:
        prerequisite_missing("playwright not installed; run `uv sync`")
    with playwright.sync_playwright() as p:
        try:
            browser = _launch(p.chromium)
        except Exception as exc:  # pragma: no cover - environment-dependent
            prerequisite_missing(
                f"no chromium available (`uv run playwright install chromium`): {exc}"
            )
        yield browser
        browser.close()


@pytest.fixture
def app_options() -> dict[str, Any]:
    """``create_app``'s keyword arguments. A module overrides this fixture to
    serve the app with doubles -- fake AI providers, the in-memory market."""
    return {}


@pytest.fixture
def calibrator_server(
    workspace_root: Path, prerequisite_missing, app_options: dict[str, Any]
) -> Iterator[str]:
    """Runs the real app against a throwaway copy of the fixture workspace and
    yields its base URL. Any template.yaml the browser saves lands in that copy,
    so a test can assert on the file the UI actually wrote."""
    if not FRONTEND_DIST.is_dir():
        prerequisite_missing(
            "src/ui/dist is absent -- run `npm run build` in src/ui to exercise the browser tests"
        )

    workspace = Workspace.discover(root_override=workspace_root)
    port = _free_port()
    config = uvicorn.Config(
        create_app(workspace, **app_options), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = threading.Event()
    for _ in range(STARTUP_TIMEOUT_SECONDS * 20):
        if server.started:
            break
        deadline.wait(0.05)
    else:  # pragma: no cover - only on a pathologically slow machine
        server.should_exit = True
        pytest.fail("calibrator server did not start in time")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop_server(server, thread)


DEFAULT_TIMEOUT_MS = 60_000
"""Headroom over Playwright's 30s default, because every wait in this layer
sits behind the *real* render pipeline running in-process -- and under
`pytest --cov`, which is how `scripts/check.sh` runs it, that is meaningfully
slower than a normal browser interaction.

It buys margin; it is not a fix for anything. A wait here that actually
exhausts 60s is reporting a bug, not a slow machine -- the last one to do so
was a stale closure in the upload form that meant the request was never sent
at all."""


@pytest.fixture
def page(browser_type, calibrator_server: str):  # noqa: ANN001, ANN201
    context = browser_type.new_context(viewport={"width": 1280, "height": 900})
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    context.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
    page = context.new_page()
    # Phase 5 mounts the calibrator at /templates under the new app shell,
    # unchanged -- the bare origin now serves the Dashboard stub instead.
    page.goto(f"{calibrator_server}/templates")
    yield page
    context.close()

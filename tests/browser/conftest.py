"""Serves the calibrator the way `etsy-listings ui` does -- FastAPI hosting the
built SPA plus /api -- so the browser tests exercise the production shape, not
a Vite dev server that only exists on a developer's machine.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from etsy_listings.ui.api.app import FRONTEND_DIST, create_app
from etsy_listings.workspace.workspace import Workspace

STARTUP_TIMEOUT_SECONDS = 30


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def browser_type():  # noqa: ANN201 - playwright's type isn't worth importing at module scope
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright not installed; run `uv sync`"
    )
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"no chromium available (`uv run playwright install chromium`): {exc}")
        yield browser
        browser.close()


@pytest.fixture
def calibrator_server(workspace_root: Path) -> Iterator[str]:
    """Runs the real app against a throwaway copy of the fixture workspace and
    yields its base URL. Any template.yaml the browser saves lands in that copy,
    so a test can assert on the file the UI actually wrote."""
    if not FRONTEND_DIST.is_dir():
        pytest.skip(
            "ui/frontend/dist is absent -- run `npm run build` in "
            "src/etsy_listings/ui/frontend to exercise the browser tests"
        )

    workspace = Workspace.discover(root_override=workspace_root)
    port = _free_port()
    config = uvicorn.Config(create_app(workspace), host="127.0.0.1", port=port, log_level="warning")
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
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def page(browser_type, calibrator_server: str):  # noqa: ANN001, ANN201
    context = browser_type.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.goto(calibrator_server)
    yield page
    context.close()

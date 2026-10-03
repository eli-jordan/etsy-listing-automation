"""The ``ui`` command serves the HTTP app in the foreground.

A behaviour test rather than a unit one because it drives the Typer
application: the interesting facts are that the command reaches uvicorn with
the workspace's app, its host and its port, and that nothing on that path
needs a GUI toolkit. The module-structure specification removed the native
window and its ``--browser``/``--debug`` flags (ADR-0052), so those are
rejected as unknown options rather than accepted and ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from etsy_listings.cli.app import app

runner = CliRunner()


def _capture_uvicorn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Record what the command hands uvicorn, and block the GUI toolkit.

    A `None` entry makes any `import webview` raise ImportError, so a path
    that still reached for the toolkit fails here instead of opening a window
    on the machine running the tests.
    """
    monkeypatch.setitem(sys.modules, "webview", None)
    seen: dict[str, Any] = {}

    def fake_run(served: object, **kwargs: Any) -> None:
        seen["app"] = served
        seen.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    return seen


def test_bare_ui_serves_http_without_a_gui_toolkit(
    monkeypatch: pytest.MonkeyPatch, workspace_root: Path
) -> None:
    seen = _capture_uvicorn(monkeypatch)

    result = runner.invoke(app, ["ui", "--root", str(workspace_root)])

    assert result.exit_code == 0, result.output
    served = seen["app"]
    assert isinstance(served, FastAPI)
    assert served.state.workspace.root == workspace_root.resolve()
    # Every interface, not loopback: the workspace is reachable from a phone
    # or another machine on the LAN, which is the point of serving it at all.
    assert seen["host"] == "0.0.0.0"
    assert seen["port"] == 8000


def test_ui_passes_host_and_port_to_the_server(
    monkeypatch: pytest.MonkeyPatch, workspace_root: Path
) -> None:
    seen = _capture_uvicorn(monkeypatch)

    result = runner.invoke(
        app, ["ui", "--host", "127.0.0.1", "--port", "9000", "--root", str(workspace_root)]
    )

    assert result.exit_code == 0, result.output
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 9000


@pytest.mark.parametrize("flag", ["--browser", "--debug"])
def test_removed_native_window_flags_are_rejected(
    flag: str, monkeypatch: pytest.MonkeyPatch, workspace_root: Path
) -> None:
    seen = _capture_uvicorn(monkeypatch)

    result = runner.invoke(app, ["ui", flag, "--root", str(workspace_root)])

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert seen == {}

"""The ``ui`` command's flags reach the desktop launcher.

A behaviour test rather than a unit one because it drives the Typer
application: the interesting fact is that ``--browser`` and ``--debug``
survive the CLI and arrive as the kwargs ``run_calibrator`` is defined to
take, not that the launcher itself does the right thing with them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from etsy_listings.cli.app import app
from etsy_listings.errors import UserFacingError
from etsy_listings.workspace.workspace import Workspace

runner = CliRunner()


def test_ui_defaults_to_a_native_window(
    monkeypatch: pytest.MonkeyPatch, workspace_root: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(workspace: Workspace, **kwargs: Any) -> None:
        seen["root"] = workspace.root
        seen.update(kwargs)

    monkeypatch.setattr("etsy_listings.ui.desktop.run_calibrator", fake_run)
    result = runner.invoke(app, ["ui", "--root", str(workspace_root)])
    assert result.exit_code == 0, result.output
    assert seen["browser"] is False
    assert seen["debug"] is False
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8000


def test_ui_browser_flag_skips_the_native_window(
    monkeypatch: pytest.MonkeyPatch, workspace_root: Path
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(workspace: Workspace, **kwargs: Any) -> None:
        seen.update(kwargs)

    monkeypatch.setattr("etsy_listings.ui.desktop.run_calibrator", fake_run)
    result = runner.invoke(
        app, ["ui", "--browser", "--debug", "--port", "9000", "--root", str(workspace_root)]
    )
    assert result.exit_code == 0, result.output
    assert seen["browser"] is True
    assert seen["debug"] is True
    assert seen["port"] == 9000


def test_ui_prints_a_user_facing_error(
    monkeypatch: pytest.MonkeyPatch, workspace_root: Path
) -> None:
    def fake_run(workspace: Workspace, **kwargs: Any) -> None:
        raise UserFacingError("the calibrator frontend has not been built")

    monkeypatch.setattr("etsy_listings.ui.desktop.run_calibrator", fake_run)
    result = runner.invoke(app, ["ui", "--root", str(workspace_root)])
    assert result.exit_code == 1
    assert "has not been built" in result.output

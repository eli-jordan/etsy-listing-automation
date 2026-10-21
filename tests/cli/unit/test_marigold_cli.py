from pathlib import Path

from typer.testing import CliRunner

from etsy_listings.cli.app import app


def test_marigold_status_reports_setup_without_creating_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = CliRunner().invoke(app, ["marigold", "status"])
    assert result.exit_code == 0
    assert "etsy-listings marigold setup" in result.output
    assert not (tmp_path / ".etsy-listings").exists()

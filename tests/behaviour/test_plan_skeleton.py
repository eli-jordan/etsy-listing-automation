"""Phase 0 exit criterion: ``plan`` runs against a fixture workspace with no
network beyond the catalog -- and since no stage exists yet to touch the
catalog, this exercises the full CLI path with zero network calls at all."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from etsy_listings.cli.app import app

runner = CliRunner()


def test_plan_single_listing_against_fixture_workspace(workspace_root: Path) -> None:
    result = runner.invoke(app, ["plan", "take-a-hike", "--root", str(workspace_root)])
    assert result.exit_code == 0, result.output
    assert "take-a-hike" in result.output
    assert "no stages configured" in result.output


def test_plan_all_against_fixture_workspace(workspace_root: Path) -> None:
    result = runner.invoke(app, ["plan", "--all", "--root", str(workspace_root)])
    assert result.exit_code == 0, result.output
    assert "take-a-hike" in result.output


def test_plan_unknown_listing_fails_with_message(workspace_root: Path) -> None:
    result = runner.invoke(app, ["plan", "does-not-exist", "--root", str(workspace_root)])
    assert result.exit_code != 0
    assert "does-not-exist" in result.output


def test_plan_requires_listing_or_all(workspace_root: Path) -> None:
    result = runner.invoke(app, ["plan", "--root", str(workspace_root)])
    assert result.exit_code != 0


def test_plan_surfaces_actionable_config_error(workspace_root: Path) -> None:
    listing_path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    listing_path.write_text(listing_path.read_text().replace("349 NOK", "349"))

    result = runner.invoke(app, ["plan", "take-a-hike", "--root", str(workspace_root)])
    assert result.exit_code != 0
    assert "bare number" in result.output

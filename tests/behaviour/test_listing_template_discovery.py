"""A listing template is never a listing (spec, *Product invariants* 1; A35).

It never appears in listing discovery, ``plan --all``, or the workspace-wide
deploy the listings table starts. Nothing filters it out: it lives beside
``listings/``, not in it, and these tests pin that every entry point that
enumerates listings still asks only ``listings/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from etsy_listings.cli.app import app as cli
from etsy_listings.listing_templates import from_listing, save
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING

TEMPLATE = "hike-template"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    workspace = Workspace.discover(root_override=workspace_root)
    save(
        workspace,
        TEMPLATE,
        from_listing(workspace, FIXTURE_LISTING),
        facts=WorkspaceFacts.gather(workspace),
    )
    assert workspace.listing_template_names() == [TEMPLATE]
    return workspace


def test_listing_discovery_never_includes_a_template(workspace: Workspace) -> None:
    assert workspace.listing_names() == [FIXTURE_LISTING]


def test_plan_all_never_plans_a_template(workspace: Workspace) -> None:
    result = CliRunner().invoke(cli, ["plan", "--all", "--root", str(workspace.root)])

    assert result.exit_code == 0, result.output
    assert FIXTURE_LISTING in result.output
    assert TEMPLATE not in result.output


def test_the_listings_table_and_a_workspace_deploy_never_include_a_template(
    workspace: Workspace,
) -> None:
    client = TestClient(create_app(workspace))

    table = client.get("/api/listings").json()
    run = client.post("/api/runs", json={"kind": "plan", "scope": "workspace"})

    assert [row["name"] for row in table] == [FIXTURE_LISTING]
    assert run.status_code == 202
    assert run.json()["listings"] == [FIXTURE_LISTING]

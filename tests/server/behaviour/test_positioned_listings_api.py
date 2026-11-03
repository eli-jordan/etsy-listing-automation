"""The calibrator's read of which listings hold positions for a template
(spec, *Recalibration*; ADR-0058). It names them and never edits one."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.clients import FakeClients

BOX = [
    {"x": 144, "y": 126.72},
    {"x": 345.6, "y": 115.2},
    {"x": 355.2, "y": 391.68},
    {"x": 134.4, "y": 403.2},
]
URL = "/api/listings/take-a-hike"


@pytest.fixture
def client(workspace_root: Path, fake_clients: FakeClients) -> TestClient:
    return TestClient(
        create_app(
            Workspace.discover(root_override=workspace_root), clients=fake_clients.factories()
        )
    )


def test_calibrator_reads_which_listings_hold_positions_for_a_template(
    client: TestClient,
    workspace_root: Path,
) -> None:
    """Spec, *Recalibration*: what the calibrator names before and after a save."""
    client.patch(
        URL,
        json={
            "template_positions": {
                "colour-chart-01": {"placements": {"fixture-placement-1": {"bounding_box": BOX}}}
            }
        },
    )
    listing = Workspace.discover(root_override=workspace_root).listing_file("take-a-hike")
    before = listing.read_bytes()

    held = client.get("/api/templates/colour-chart-01/positioned-listings")
    assert held.status_code == 200
    assert held.json() == [{"listing": "take-a-hike", "placements": ["fixture-placement-1"]}]
    assert client.get("/api/templates/flat-lay-01/positioned-listings").json() == []
    assert client.get("/api/templates/no-such/positioned-listings").status_code == 404
    assert listing.read_bytes() == before

"""PATCH keeps positioned listing source and reports current position issues."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.clients import FakeClients
from tests.support.source_files import identity

SOURCE = """# The seller's notes: café.
garment_profile: comfort-colors-1717
design: {default: designs/take-a-hike.png}  # keep this spelling
colors: [black]
brief: 'Original'  # a note
prices: {S: 349 NOK}
media: [{template: flat-lay-01, colour: black}]
"""
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


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_positions_patch_round_trip_and_reset_preserve_source_bytes(
    client: TestClient,
    workspace_root: Path,
    newline: str,
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    path = workspace.listing_file("take-a-hike")
    source = SOURCE.replace("\n", newline).encode()
    path.write_bytes(source)
    positions = {"flat-lay-01": {"bounding_box": BOX}}
    response = client.patch(URL, json={"template_positions": positions})
    assert response.status_code == 200
    assert response.json()["field_errors"] == {}
    assert response.json()["template_positions"] == positions
    assert path.read_bytes().startswith(source)
    positioned = path.read_bytes()
    before = identity(path)
    client.patch(URL, json={"template_positions": positions})
    assert path.read_bytes() == positioned
    assert identity(path) == before
    reset = client.patch(URL, json={"template_positions": None})
    assert reset.json()["template_positions"] is None
    assert path.read_bytes() == source


def test_unrelated_save_keeps_positions_and_their_comments(
    client: TestClient,
    workspace_root: Path,
) -> None:
    path = Workspace.discover(root_override=workspace_root).listing_file("take-a-hike")
    path.write_bytes(SOURCE.encode())
    client.patch(URL, json={"template_positions": {"flat-lay-01": {"bounding_box": BOX}}})
    path.write_bytes(
        path.read_bytes().replace(b"template_positions:", b"template_positions: # mine")
    )
    section = path.read_bytes().split(b"template_positions:")[1]
    response = client.patch(URL, json={"brief": "Changed"})
    assert response.json()["template_positions"] == {"flat-lay-01": {"bounding_box": BOX}}
    assert path.read_bytes().split(b"template_positions:")[1] == section


def test_stale_positions_save_and_report_a_blocking_images_issue(client: TestClient) -> None:
    response = client.patch(URL, json={"template_positions": {"removed": {"bounding_box": BOX}}})
    assert response.json()["field_errors"] == {}
    issue = next(
        issue for issue in response.json()["issues"] if "template_positions" in issue["where"]
    )
    assert issue["severity"] == "block"
    assert issue["tab"] == "images"
    assert (
        issue["message"]
        == "take-a-hike: template_positions.removed names a template that is not in media"
    )


def test_unreadable_settings_are_a_listing_issue_not_a_failed_read(
    client: TestClient, workspace_root: Path
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    workspace.listing_file("take-a-hike").write_bytes(SOURCE.encode())
    client.patch(URL, json={"template_positions": {"flat-lay-01": {"bounding_box": BOX}}})
    workspace.settings_file().write_bytes(b"template_positions:\n  rotation: lots\n")

    detail = client.get(URL)
    assert detail.status_code == 200
    blocking = [i for i in detail.json()["issues"] if i["severity"] == "block"]
    assert any(
        "settings.yaml" in i["message"] and "template_positions.rotation" in i["message"]
        for i in blocking
    )
    assert client.get("/api/listings").status_code == 200

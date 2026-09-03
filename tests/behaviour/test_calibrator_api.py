"""Behaviour tests for the calibrator's FastAPI endpoints, run through the real
render pipeline against the fixture workspace's synthetic template -- no
network, no browser."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace))


def test_list_templates_includes_fixture_template(client: TestClient) -> None:
    response = client.get("/api/templates")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert "flat-lay-01" in names


def test_get_config_returns_the_fixture_quad(client: TestClient) -> None:
    response = client.get("/api/templates/flat-lay-01/config")
    assert response.status_code == 200
    body = response.json()
    assert len(body["warp"]["quad"]) == 4
    assert body["shade"]["enabled"] is True


def test_get_config_404s_for_unknown_template(client: TestClient) -> None:
    response = client.get("/api/templates/does-not-exist/config")
    assert response.status_code == 404


def test_put_config_updates_the_quad(client: TestClient) -> None:
    current = client.get("/api/templates/flat-lay-01/config").json()
    new_quad = [[10, 10], [200, 10], [200, 200], [10, 200]]
    current["warp"]["quad"] = new_quad

    put_response = client.put("/api/templates/flat-lay-01/config", json=current)
    assert put_response.status_code == 200
    assert put_response.json()["warp"]["quad"] == new_quad

    get_response = client.get("/api/templates/flat-lay-01/config")
    assert get_response.json()["warp"]["quad"] == new_quad


def test_preview_renders_a_real_png_through_the_renderer(client: TestClient) -> None:
    config = client.get("/api/templates/flat-lay-01/config").json()
    response = client.post(
        "/api/templates/flat-lay-01/preview",
        json={"colour": "black", **config},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_preview_unknown_colour_404s(client: TestClient) -> None:
    config = client.get("/api/templates/flat-lay-01/config").json()
    response = client.post(
        "/api/templates/flat-lay-01/preview",
        json={"colour": "not-a-real-colour", **config},
    )
    assert response.status_code == 404


def test_upload_creates_a_new_template_with_default_config(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    image_path = tmp_path / "teal.png"
    Image.new("RGB", (200, 240), (10, 100, 120)).save(image_path)

    with image_path.open("rb") as f:
        response = client.post(
            "/api/templates",
            params={"name": "brand-new-template"},
            files=[("files", ("teal.png", f, "image/png"))],
        )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "brand-new-template"
    assert body["colours"] == ["teal"]

    config_response = client.get("/api/templates/brand-new-template/config")
    assert config_response.status_code == 200


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

"""Behaviour tests for the calibrator's FastAPI endpoints, run through the real
render pipeline against the fixture workspace's synthetic templates -- no
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


def test_list_templates_includes_fixture_templates_with_kind(client: TestClient) -> None:
    response = client.get("/api/templates")
    assert response.status_code == 200
    by_name = {t["name"]: t for t in response.json()}
    assert by_name["flat-lay-01"]["kind"] == "colour-matrix"
    assert by_name["colour-chart-01"]["kind"] == "multiple"


def test_list_templates_includes_a_directory_with_no_template_yaml(
    client: TestClient, workspace_root: Path
) -> None:
    """The calibrator is what writes template.yaml, so an uncalibrated
    directory has to be listable -- otherwise there is no way to select it and
    calibrate it."""
    (workspace_root / "mockup-templates" / "not-calibrated-yet").mkdir()
    by_name = {t["name"]: t for t in client.get("/api/templates").json()}
    assert by_name["not-calibrated-yet"] == {
        "name": "not-calibrated-yet",
        "kind": None,
        "colours": [],
        "has_config": False,
    }


def test_get_config_returns_the_fixture_bounding_box(client: TestClient) -> None:
    response = client.get("/api/templates/flat-lay-01/config")
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "colour-matrix"
    assert len(body["bounding_box"]) == 4
    assert set(body["bounding_box"][0]) == {"x", "y"}
    assert body["shade"]["enabled"] is True


def test_get_config_404s_for_unknown_template(client: TestClient) -> None:
    response = client.get("/api/templates/does-not-exist/config")
    assert response.status_code == 404


def test_put_config_updates_the_bounding_box(client: TestClient) -> None:
    current = client.get("/api/templates/flat-lay-01/config").json()
    new_box = [{"x": 10, "y": 10}, {"x": 200, "y": 10}, {"x": 200, "y": 200}, {"x": 10, "y": 200}]
    current["bounding_box"] = new_box

    put_response = client.put("/api/templates/flat-lay-01/config", json=current)
    assert put_response.status_code == 200
    assert put_response.json()["bounding_box"] == new_box

    get_response = client.get("/api/templates/flat-lay-01/config")
    assert get_response.json()["bounding_box"] == new_box


def test_preview_renders_a_real_png_through_the_renderer_for_colour_matrix(
    client: TestClient,
) -> None:
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


def test_preview_renders_the_full_composite_for_multiple_kind(client: TestClient) -> None:
    config = client.get("/api/templates/colour-chart-01/config").json()
    assert len(config["placements"]) == 2
    response = client.post("/api/templates/colour-chart-01/preview", json=config)
    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_wrong_body_shape_for_kind_is_rejected(client: TestClient) -> None:
    """Posting a colour-matrix-shaped body at a multiple-kind template is a
    client error, not silently mis-rendered."""
    response = client.post(
        "/api/templates/colour-chart-01/preview",
        json={
            "colour": "black",
            "bounding_box": [
                {"x": 0, "y": 0},
                {"x": 100, "y": 0},
                {"x": 100, "y": 100},
                {"x": 0, "y": 100},
            ],
        },
    )
    assert response.status_code in (400, 422)


def test_upload_colour_matrix_creates_a_new_template_with_default_config(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    image_path = tmp_path / "teal.png"
    Image.new("RGB", (200, 240), (10, 100, 120)).save(image_path)

    with image_path.open("rb") as f:
        response = client.post(
            "/api/templates",
            params={"name": "brand-new-template", "kind": "colour-matrix"},
            files=[("files", ("teal.png", f, "image/png"))],
        )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "brand-new-template"
    assert body["kind"] == "colour-matrix"
    assert body["colours"] == ["teal"]

    config_response = client.get("/api/templates/brand-new-template/config")
    assert config_response.status_code == 200
    assert config_response.json()["kind"] == "colour-matrix"


def test_upload_single_kind_saves_scene_png_regardless_of_uploaded_filename(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    image_path = tmp_path / "lifestyle-shot.png"
    Image.new("RGB", (200, 240), (10, 100, 120)).save(image_path)

    with image_path.open("rb") as f:
        response = client.post(
            "/api/templates",
            params={"name": "lifestyle-01", "kind": "single"},
            files=[("files", ("lifestyle-shot.png", f, "image/png"))],
        )
    assert response.status_code == 200
    assert response.json()["kind"] == "single"

    config_response = client.get("/api/templates/lifestyle-01/config")
    assert config_response.json()["kind"] == "single"


def test_upload_multiple_kind_rejects_more_than_one_file(
    client: TestClient, tmp_path: Path
) -> None:
    from PIL import Image

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(a)
    Image.new("RGB", (100, 100), (0, 0, 0)).save(b)

    with a.open("rb") as fa, b.open("rb") as fb:
        response = client.post(
            "/api/templates",
            params={"name": "two-photo-chart", "kind": "multiple"},
            files=[("files", ("a.png", fa, "image/png")), ("files", ("b.png", fb, "image/png"))],
        )
    assert response.status_code == 400


def test_traversal_template_name_is_rejected_not_resolved(client: TestClient) -> None:
    """Template names arrive from the URL. They go through the workspace's
    layout accessors, so a traversal attempt is refused by the same rule that
    guards every other path (A8) rather than by a check local to the web layer."""
    response = client.get("/api/templates/..%2F..%2Fetc/config")
    assert response.status_code in (400, 404)
    assert "shop.yaml" not in response.text


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

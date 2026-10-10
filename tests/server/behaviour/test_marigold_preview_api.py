"""Full-quality CPU previews with durable maps and no runtime access."""

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.marigold import material_maps


@pytest.mark.parametrize("kind", ["single", "colour-matrix", "multiple"])
def test_prepared_preview_is_full_quality_and_refuses_unsaved_geometry(
    workspace_root: Path, kind: str
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    name = "prepared"
    workspace.template_dir(name).mkdir()
    photo = workspace.template_dir(name) / ("navy.png" if kind == "colour-matrix" else "scene.png")
    Image.new("RGB", (16, 16), "navy").save(photo)
    box = [{"x": x, "y": y} for x, y in [(0, 0), (15, 0), (15, 15), (0, 15)]]
    config = {"kind": kind, "renderer": {"type": "marigold", "config": {}}}
    if kind == "multiple":
        config["placements"] = [
            {"id": identity, "colour": "Navy", "bounding_box": box}
            for identity in ["left", "right"]
        ]
    else:
        config["bounding_box"] = box
    workspace.save_template_config(name, load_template_config(config))
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs(name)
    maps = {placement.id: material_maps() for placement in inputs.placements}
    artifacts.publish(name, inputs, maps, current_inputs=lambda: artifacts.saved_inputs(name))
    client = TestClient(create_app(workspace))
    body = {**config, "design": "bundled-grid"}
    if kind == "colour-matrix":
        body["colour"] = "navy"
    response = client.post(f"/api/templates/{name}/preview", json=body)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert len(response.headers["x-render-identity"]) == 71
    assert response.headers["x-map-generation"]
    assert Image.open(BytesIO(response.content)).size == (16, 16)
    assert (
        response.content
        == client.get(
            f"/api/templates/{name}/design-preview",
            params={
                "test_design": "bundled-grid",
                **({"colour": "navy"} if kind == "colour-matrix" else {}),
            },
        ).content
    )
    body["renderer"]["config"] = {"appearance": {"lighting_strength": 0}}
    appearance = client.post(f"/api/templates/{name}/preview", json=body)
    assert appearance.status_code == 200
    assert appearance.headers["x-render-identity"] != response.headers["x-render-identity"]
    if kind == "multiple":
        body["placements"][0]["bounding_box"][0]["x"] = 1
    else:
        body["bounding_box"][0]["x"] = 1
    stale = client.post(f"/api/templates/{name}/preview", json=body)
    assert stale.status_code == 409
    assert "prepare" in stale.json()["detail"].lower()


def test_shared_colour_dimension_mismatch_is_actionable_before_preview(
    workspace_root: Path,
) -> None:
    from tests.support.marigold import marigold_template

    workspace = marigold_template(workspace_root, "colour-matrix")
    photo = workspace.template_dir("shirt") / "navy.png"
    Image.new("RGB", (65, 64), "navy").save(photo)
    client = TestClient(create_app(workspace))
    status = client.get("/api/templates/shirt/preparation").json()
    assert status["maps"]["can_render"] is False
    assert status["maps"]["reason"] == "incompatible_dimensions"


def test_decoded_artwork_dimensions_are_part_of_preview_identity(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    name = "identity-shirt"
    workspace.template_dir(name).mkdir()
    Image.new("RGB", (16, 16), "navy").save(workspace.template_scene_image(name))
    config = {
        "kind": "single",
        "renderer": {"type": "marigold", "config": {}},
        "bounding_box": [{"x": x, "y": y} for x, y in [(0, 0), (15, 0), (15, 15), (0, 15)]],
    }
    workspace.save_template_config(name, load_template_config(config))
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs(name)
    artifacts.publish(
        name, inputs, {None: material_maps()}, current_inputs=lambda: artifacts.saved_inputs(name)
    )
    client = TestClient(create_app(workspace))
    identities = []
    outputs = []
    pixels = bytes([255, 0, 0, 255, 0, 255, 0, 255] * 4)
    for label, size in [("portrait", (2, 4)), ("landscape", (4, 2))]:
        buffer = BytesIO()
        Image.frombytes("RGBA", size, pixels).save(buffer, format="PNG")
        uploaded = client.post(
            "/api/designs", files={"file": (label + ".png", buffer.getvalue(), "image/png")}
        )
        assert uploaded.status_code == 200
        preview = client.post(
            f"/api/templates/{name}/preview", json={**config, "design": uploaded.json()["id"]}
        )
        assert preview.status_code == 200
        identities.append(preview.headers["x-render-identity"])
        outputs.append(preview.content)
    assert outputs[0] != outputs[1]
    assert identities[0] != identities[1]

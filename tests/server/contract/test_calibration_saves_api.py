"""Revision and receipt guarantees through the calibrator HTTP boundary."""

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.workspace import Workspace
from etsy_listings.server.api.app import create_app


def test_save_requires_revision_and_replays_exact_receipt(workspace_root: Path) -> None:
    client = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
    url = "/api/templates/flat-lay-01/config"
    loaded = client.get(url)
    body = {"request_id": "first-save", "config": loaded.json(), "mask_edits": []}
    assert client.put(url, json=body).status_code == 422
    saved = client.put(url, json=body, headers={"If-Match": loaded.headers["etag"]})
    assert saved.status_code == 200
    assert saved.headers["etag"]
    retry = client.put(url, json=body, headers={"If-Match": loaded.headers["etag"]})
    assert retry.json() == saved.json()
    assert retry.headers["etag"] == saved.headers["etag"]
    body["config"]["renderer"]["config"]["shade"]["opacity"] = 0.2
    assert (
        client.put(url, json=body, headers={"If-Match": loaded.headers["etag"]}).status_code == 409
    )
    body["request_id"] = "second-save"
    newer = client.put(url, json=body, headers={"If-Match": saved.headers["etag"]})
    assert newer.status_code == 200
    body["request_id"] = "stale-save"
    assert (
        client.put(url, json=body, headers={"If-Match": loaded.headers["etag"]}).status_code == 412
    )


def test_save_refuses_wrong_kind_and_brush_outside_photo(workspace_root: Path) -> None:
    from io import BytesIO

    from PIL import Image

    from etsy_listings.core.workspace.calibration import CalibrationStore

    from tests.support.marigold import marigold_template

    workspace = marigold_template(workspace_root)
    store = CalibrationStore(workspace)
    current = store.read("shirt")
    mask = BytesIO()
    Image.new("L", (64, 64), 255).save(mask, format="PNG")
    store.install_automatic(
        "shirt", mask.getvalue(), algorithm_version="test", expected_revision=current.revision
    )
    client = TestClient(create_app(workspace))
    url = "/api/templates/shirt/config"
    loaded = client.get(url)
    config = loaded.json()
    malformed = {**config, "kind": "multiple", "placements": []}
    malformed.pop("bounding_box")
    malformed.pop("colour", None)
    malformed.pop("artwork", None)
    assert (
        client.put(
            url,
            headers={"If-Match": loaded.headers["etag"]},
            json={"request_id": "kind", "config": malformed},
        ).status_code
        == 400
    )
    response = client.put(
        url,
        headers={"If-Match": loaded.headers["etag"]},
        json={
            "request_id": "outside",
            "config": config,
            "mask_edits": [
                {
                    "operations": [
                        {"type": "stroke", "mode": "mask", "diameter_px": 10, "points": [[64, 30]]}
                    ]
                }
            ],
        },
    )
    assert response.status_code == 422
    assert client.get(url).headers["etag"] == loaded.headers["etag"]

"""Real queue, automatic masks, Save rebuild and CPU preview over HTTP."""

import base64
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.server.api.app import create_app

from tests.support.marigold import PreparationRuntime, marigold_template


def wait_job(client, identity):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = client.get(f"/api/preparation/jobs/{identity}").json()
        if result["phase"] in {"completed", "failed", "cancelled", "superseded"}:
            assert result["phase"] == "completed", result
            return result
        time.sleep(0.02)
    raise AssertionError("Controlled preparation did not finish")


@pytest.mark.parametrize("kind", ["single", "colour-matrix", "multiple"])
def test_save_prepare_mask_undo_reset_and_preview_use_current_revision(
    workspace_root: Path, kind: str
) -> None:
    workspace = marigold_template(workspace_root, kind)
    runtime = PreparationRuntime()
    with TestClient(create_app(workspace, preparation_runtime=runtime)) as client:
        status_url = "/api/templates/shirt/preparation"
        status = client.get(status_url).json()
        assert status["maps"]["state"] == "needs_preparation"
        created = client.post(
            "/api/preparation/jobs",
            json={
                "template": "shirt",
                "config_revision": status["config_revision"],
                "request_id": "explicit",
            },
        )
        assert created.status_code == 202, created.text
        wait_job(client, created.json()["id"])
        ready = client.get(status_url).json()
        assert ready["maps"]["can_render"] is True
        assert all(item["mask_available"] for item in ready["placements"])
        assert ready["prepared_engine"] == "1.0.0"
        calls = sum(len(worker.calls) for worker in runtime.workers)
        mask_url = (
            "/api/templates/shirt/placements/left-shirt/mask"
            if kind == "multiple"
            else "/api/templates/shirt/mask"
        )
        baseline = client.get(mask_url, params={"source": "automatic"}).content
        config_url = "/api/templates/shirt/config"
        loaded = client.get(config_url)
        edit = {
            "operations": [
                {
                    "type": "stroke",
                    "mode": "mask",
                    "diameter_px": 12,
                    "points": [[28, 28], [32, 32]],
                }
            ]
        }
        if kind == "multiple":
            edit["placement_id"] = "left-shirt"
        painted = client.put(
            config_url,
            headers={"If-Match": loaded.headers["etag"]},
            json={"request_id": "paint", "config": loaded.json(), "mask_edits": [edit]},
        )
        assert painted.status_code == 200, painted.text
        raster = Image.open(BytesIO(client.get(mask_url).content))
        assert raster.getpixel((30, 30)) == 0
        history = client.get(mask_url + "-history").json()
        assert history["undo_count"] == 1
        assert base64.b64decode(history["strokes"][0]["before"]) == baseline
        state = client.get(status_url).json()
        if state["active_job"]:
            wait_job(client, state["active_job"]["id"])
        assert sum(len(worker.calls) for worker in runtime.workers) == calls
        edit["operations"] = [{"type": "undo"}]
        undone = client.put(
            config_url,
            headers={"If-Match": painted.headers["etag"]},
            json={"request_id": "undo", "config": painted.json(), "mask_edits": [edit]},
        )
        assert undone.status_code == 200, undone.text
        assert client.get(mask_url).content == baseline
        edit["operations"] = [{"type": "reset"}]
        reset = client.put(
            config_url,
            headers={"If-Match": undone.headers["etag"]},
            json={"request_id": "reset", "config": undone.json(), "mask_edits": [edit]},
        )
        assert reset.status_code == 200
        state = client.get(status_url).json()
        if state["active_job"]:
            wait_job(client, state["active_job"]["id"])
        assert client.get(status_url).json()["maps"]["can_render"] is True
        body = {**reset.json(), "design": "bundled-grid"}
        if kind == "colour-matrix":
            body["colour"] = "navy"
        preview = client.post("/api/templates/shirt/preview", json=body)
        assert preview.status_code == 200, preview.text
        assert Image.open(BytesIO(preview.content)).size == (64, 64)
        assert sum(len(worker.calls) for worker in runtime.workers) == calls


@pytest.mark.parametrize("kind", ["single", "colour-matrix", "multiple"])
def test_changed_photo_requires_explicit_mask_reset_and_prepare(
    workspace_root: Path, kind: str
) -> None:
    workspace = marigold_template(workspace_root, kind)
    runtime = PreparationRuntime()
    with TestClient(create_app(workspace, preparation_runtime=runtime)) as client:
        status_url = "/api/templates/shirt/preparation"
        state = client.get(status_url).json()
        request = {
            "template": "shirt",
            "config_revision": state["config_revision"],
            "request_id": "initial",
        }
        initial = client.post("/api/preparation/jobs", json=request)
        assert initial.status_code == 202
        wait_job(client, initial.json()["id"])
        calls = sum(len(worker.calls) for worker in runtime.workers)
        photo = workspace.template_main_photo("shirt")
        with Image.open(photo) as source:
            changed = source.convert("RGB")
        changed.putpixel((30, 30), (17, 23, 41))
        changed.save(photo)
        state = client.get(status_url).json()
        assert state["maps"]["reason"] == "photo_changed"
        assert all(not item["mask_available"] for item in state["placements"])
        request.update(config_revision=state["config_revision"], request_id="ordinary")
        assert client.post("/api/preparation/jobs", json=request).status_code == 409
        assert sum(len(worker.calls) for worker in runtime.workers) == calls
        request.update(request_id="recovery", action="prepare_again", reset_masks_for_photo=True)
        recovery = client.post("/api/preparation/jobs", json=request)
        assert recovery.status_code == 202, recovery.text
        retry = client.post("/api/preparation/jobs", json=request)
        assert retry.status_code == 202
        assert retry.json()["id"] == recovery.json()["id"]
        wait_job(client, recovery.json()["id"])
        ready_state = client.get(status_url).json()
        assert ready_state["maps"]["can_render"] is True
        assert all(item["mask_available"] for item in ready_state["placements"])
        assert len(client.get("/api/preparation/jobs").json()) == 2
        assert sum(len(worker.calls) for worker in runtime.workers) == calls + 3

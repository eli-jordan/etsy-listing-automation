"""Real queue, automatic masks, Save rebuild and CPU preview over HTTP."""

import base64
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from etsy_listings.core.workspace.template_state import template_state
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


STATUS_URL = "/api/templates/shirt/preparation"
CONFIG_URL = "/api/templates/shirt/config"


def worker_calls(runtime):
    return sum(len(worker.calls) for worker in runtime.workers)


def mask_url(kind):
    if kind == "multiple":
        return "/api/templates/shirt/placements/left-shirt/mask"
    return "/api/templates/shirt/mask"


def prepare(client, request_id):
    """Prepare the template at its current revision and wait for the job."""
    status = client.get(STATUS_URL).json()
    created = client.post(
        "/api/preparation/jobs",
        json={
            "template": "shirt",
            "config_revision": status["config_revision"],
            "request_id": request_id,
        },
    )
    assert created.status_code == 202, created.text
    wait_job(client, created.json()["id"])


def settle(client):
    """Wait for whatever rebuild a save queued."""
    state = client.get(STATUS_URL).json()
    if state["active_job"]:
        wait_job(client, state["active_job"]["id"])


def save_mask_edit(client, previous, request_id, edit):
    saved = client.put(
        CONFIG_URL,
        headers={"If-Match": previous.headers["etag"]},
        json={"request_id": request_id, "config": previous.json(), "mask_edits": [edit]},
    )
    assert saved.status_code == 200, saved.text
    return saved


@pytest.mark.parametrize("kind", ["single", "colour-matrix", "multiple"])
def test_save_prepare_mask_undo_reset_and_preview_use_current_revision(
    workspace_root: Path, kind: str
) -> None:
    workspace = marigold_template(workspace_root, kind)
    runtime = PreparationRuntime()
    with TestClient(create_app(workspace, preparation_runtime=runtime)) as client:
        status_response = client.get(STATUS_URL)
        assert status_response.headers["cache-control"] == "no-store"
        assert status_response.json()["maps"]["state"] == "needs_preparation"
        prepare(client, "explicit")
        ready = client.get(STATUS_URL).json()
        assert ready["maps"]["can_render"] is True
        assert all(item["mask_available"] for item in ready["placements"])
        assert ready["prepared_engine"] == "1.0.0"
        calls = worker_calls(runtime)
        url = mask_url(kind)
        baseline = client.get(url, params={"source": "automatic"}).content
        stroke = {
            "type": "stroke",
            "mode": "mask",
            "diameter_px": 12,
            "points": [[28, 28], [32, 32]],
        }
        edit = {"operations": [stroke]}
        if kind == "multiple":
            edit["placement_id"] = "left-shirt"
        painted = save_mask_edit(client, client.get(CONFIG_URL), "paint", edit)
        raster = Image.open(BytesIO(client.get(url).content))
        assert raster.getpixel((30, 30)) == 0
        history_response = client.get(url + "-history")
        assert history_response.headers["cache-control"] == "no-store"
        history = history_response.json()
        assert history["undo_count"] == 1
        assert base64.b64decode(history["strokes"][0]["before"]) == baseline
        settle(client)
        assert worker_calls(runtime) == calls
        edit["operations"] = [{"type": "undo"}]
        undone = save_mask_edit(client, painted, "undo", edit)
        assert client.get(url).content == baseline
        edit["operations"] = [{"type": "reset"}]
        reset = save_mask_edit(client, undone, "reset", edit)
        settle(client)
        assert client.get(STATUS_URL).json()["maps"]["can_render"] is True
        body = {**reset.json(), "design": "bundled-grid"}
        if kind == "colour-matrix":
            body["colour"] = "navy"
        preview = client.post("/api/templates/shirt/preview", json=body)
        assert preview.status_code == 200, preview.text
        assert Image.open(BytesIO(preview.content)).size == (64, 64)
        assert worker_calls(runtime) == calls


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
        photo = workspace.template_main_photo("shirt", template_state(workspace, "shirt").require())
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


def upload_white_design(client):
    buffer = BytesIO()
    Image.new("RGBA", (32, 32), "white").save(buffer, format="PNG")
    uploaded = client.post(
        "/api/designs", files={"file": ("white.png", buffer.getvalue(), "image/png")}
    )
    return uploaded.json()["id"]


def placement_ids(body, kind):
    return [p["id"] for p in body["placements"]] if kind == "multiple" else [None]


def bounding_boxes(body, kind):
    if kind == "multiple":
        return [p["bounding_box"] for p in body["placements"]]
    return [body["bounding_box"]]


EDITOR_PREVIEW_URL = "/api/templates/shirt/preview?scale=editor"
STROKE = {"type": "stroke", "mode": "mask", "diameter_px": 24, "points": [[32, 32]]}


def assert_draft_strokes_are_not_saved(client, kind, body, baseline, saved):
    """A drafted stroke changes the composite but no saved mask, calibration
    or prepared maps; undoing or resetting it restores the baseline. ``saved``
    is the loaded config response and the prepared status."""
    loaded, ready = saved
    ids = placement_ids(body, kind)
    url = mask_url(kind)
    mask_before = client.get(url).content
    body["mask_edits"] = [{"placement_id": key, "operations": [STROKE]} for key in ids]
    painted = client.post(EDITOR_PREVIEW_URL, json=body)
    assert painted.status_code == 200, painted.text
    before = Image.open(BytesIO(baseline.content)).convert("RGB")
    after = Image.open(BytesIO(painted.content)).convert("RGB")
    assert sum(before.getpixel((32, 32))) > sum(after.getpixel((32, 32))) + 200
    assert client.get(url).content == mask_before
    assert client.get(CONFIG_URL).headers["etag"] == loaded.headers["etag"]
    assert (
        client.get(STATUS_URL).json()["maps"]["content_digest"] == ready["maps"]["content_digest"]
    )
    assert client.post("/api/templates/shirt/preview", json=body).status_code == 409
    for operation in ["undo", "reset"]:
        body["mask_edits"] = [
            {"placement_id": key, "operations": [STROKE, {"type": operation}]} for key in ids
        ]
        restored = client.post(EDITOR_PREVIEW_URL, json=body)
        assert restored.status_code == 200, restored.text
        assert restored.content == baseline.content
    body["mask_edits"] = []


@pytest.mark.parametrize("kind", ["single", "multiple"])
def test_interactive_drafts_composite_without_saving_or_publishing(workspace_root, kind):
    workspace = marigold_template(workspace_root, kind)
    runtime = PreparationRuntime()
    with TestClient(create_app(workspace, preparation_runtime=runtime)) as client:
        prepare(client, "interactive-fixture")
        loaded = client.get(CONFIG_URL)
        ready = client.get(STATUS_URL).json()
        calls = worker_calls(runtime)
        body = {
            **loaded.json(),
            "design": upload_white_design(client),
            "calibration_revision": loaded.headers["etag"].strip(chr(34)),
        }
        baseline = client.post(EDITOR_PREVIEW_URL, json=body)
        assert baseline.status_code == 200, baseline.text
        assert baseline.headers["content-type"] == "image/webp"
        assert baseline.headers["x-preview-quality"] == "interactive"
        assert "x-render-identity" not in baseline.headers
        assert_draft_strokes_are_not_saved(client, kind, body, baseline, (loaded, ready))
        for box in bounding_boxes(body, kind):
            box[0]["x"] += 2
        adjusted = client.post(EDITOR_PREVIEW_URL, json=body)
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.content != baseline.content
        # Cached transient maps must still require validated retained evidence.
        # Durable readiness survives removal, but authoring must not infer.
        pointer = workspace.preparation_prediction_current("shirt")
        retained = pointer.read_bytes()
        pointer.unlink()
        assert client.post(EDITOR_PREVIEW_URL, json=body).status_code == 409
        assert client.get(STATUS_URL).json()["maps"]["can_render"]
        pointer.write_bytes(retained)
        body["calibration_revision"] = "stale"
        assert client.post(EDITOR_PREVIEW_URL, json=body).status_code == 409
        assert worker_calls(runtime) == calls


def test_interactive_colour_selection_changes_only_the_target_photo(workspace_root):
    workspace = marigold_template(workspace_root, "colour-matrix")
    runtime = PreparationRuntime()
    with TestClient(create_app(workspace, preparation_runtime=runtime)) as client:
        status_url = "/api/templates/shirt/preparation"
        status = client.get(status_url).json()
        created = client.post(
            "/api/preparation/jobs",
            json={
                "template": "shirt",
                "config_revision": status["config_revision"],
                "request_id": "colour-fixture",
            },
        )
        wait_job(client, created.json()["id"])
        ready = client.get(status_url).json()
        loaded = client.get("/api/templates/shirt/config")
        calls = sum(len(worker.calls) for worker in runtime.workers)
        outputs = {}
        for colour in ["navy", "ivory", "navy"]:
            response = client.post(
                "/api/templates/shirt/preview?scale=editor",
                json={
                    **loaded.json(),
                    "colour": colour,
                    "design": "bundled-grid",
                    "calibration_revision": ready["config_revision"],
                },
            )
            assert response.status_code == 200, response.text
            outputs[colour] = Image.open(BytesIO(response.content)).convert("RGB")
        navy = outputs["navy"].getpixel((9, 32))
        ivory = outputs["ivory"].getpixel((9, 32))
        assert navy[0] < 40, navy
        assert navy[1] < 40, navy
        assert navy[2] > 90, navy
        assert min(ivory) > 200, ivory
        after = client.get(status_url).json()
        assert after["main_photo"] == ready["main_photo"]
        assert after["maps"]["content_digest"] == ready["maps"]["content_digest"]
        assert client.get("/api/templates/shirt/config").headers["etag"] == loaded.headers["etag"]
        assert sum(len(worker.calls) for worker in runtime.workers) == calls
        Image.new("RGB", (65, 64), "navy").save(workspace.template_base_image("shirt", "navy"))
        mismatched = client.post(
            "/api/templates/shirt/preview?scale=editor",
            json={
                **loaded.json(),
                "colour": "navy",
                "design": "bundled-grid",
                "calibration_revision": ready["config_revision"],
            },
        )
        assert mismatched.status_code == 409
        assert "dimensions" in mismatched.json()["detail"].lower()

"""Read-only preparation status and explicit coordinator HTTP requests."""

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.server.api.app import create_app


def test_status_reports_reference_and_unavailable_masks_without_submitting(
    workspace_root: Path,
) -> None:
    client = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
    status = client.get("/api/templates/flat-lay-01/preparation")
    assert status.status_code == 200
    assert status.json()["maps"]["state"] == "not_required"
    assert status.json()["main_photo"] == "mockup-templates/flat-lay-01/black.png"
    assert status.json()["placements"][0]["placement_id"] is None
    assert status.json()["placements"][0]["mask_available"] is False
    summaries = {item["name"]: item for item in client.get("/api/templates").json()}
    assert summaries["flat-lay-01"]["renderer"] == "photo-warp"
    assert summaries["flat-lay-01"]["maps"]["can_render"] is True
    assert client.get("/api/preparation/jobs").json() == []
    assert client.get("/api/templates/flat-lay-01/mask").status_code == 409
    # A mask route for another kind of template names a mask it does not have.
    assert client.get("/api/templates/colour-chart-01/mask").status_code == 409
    assert client.get("/api/templates/flat-lay-01/placements/arbitrary/mask").status_code == 409


def test_explicit_submission_reconnect_and_cancel_keep_one_durable_job(
    workspace_root: Path,
) -> None:
    from etsy_listings.core.render import load_template_config

    from tests.support.marigold import PreparationRuntime

    workspace = Workspace.discover(root_override=workspace_root)
    config = template_state(workspace, "flat-lay-01").require().model_dump(mode="json")
    config["renderer"] = {"type": "marigold", "config": {}}
    CalibrationStore(workspace).write_config("flat-lay-01", load_template_config(config))
    runtime = PreparationRuntime()
    client = TestClient(create_app(workspace, preparation_runtime=runtime))
    state = client.get("/api/templates/flat-lay-01/preparation").json()
    assert runtime.inspections == 0
    body = {
        "template": "flat-lay-01",
        "config_revision": state["config_revision"],
        "request_id": "prepare-once",
        "action": "prepare",
    }
    created = client.post("/api/preparation/jobs", json=body)
    assert created.status_code == 202
    identity = created.json()["id"]
    assert client.post("/api/preparation/jobs", json=body).json()["id"] == identity
    body["action"] = "prepare_again"
    assert client.post("/api/preparation/jobs", json=body).status_code == 409
    cancelled = client.delete(f"/api/preparation/jobs/{identity}")
    assert cancelled.status_code == 200
    assert cancelled.json()["phase"] == "cancelled"
    assert client.delete(f"/api/preparation/jobs/{identity}").json() == cancelled.json()
    events = client.get(f"/api/preparation/jobs/{identity}/events")
    assert events.status_code == 200
    assert "event: snapshot" in events.text
    assert '"phase":"cancelled"' in events.text
    sequence = cancelled.json()["last_event_sequence"]
    replay = client.get(
        f"/api/preparation/jobs/{identity}/events", headers={"Last-Event-ID": str(sequence)}
    )
    assert replay.text == ""
    resync = client.get(
        f"/api/preparation/jobs/{identity}/events", headers={"Last-Event-ID": str(sequence + 100)}
    )
    assert resync.status_code == 409
    assert resync.json()["detail"]["resync"] is True
    assert len(client.get("/api/preparation/jobs").json()) == 1


def test_missing_targets_and_invalid_pagination_have_client_statuses(workspace_root: Path) -> None:
    client = TestClient(create_app(Workspace.discover(root_override=workspace_root)))
    for route in [
        "/api/templates/missing/preparation",
        "/api/templates/missing/mask",
        "/api/templates/missing/mask-history",
        "/api/preparation/jobs/missing",
        "/api/preparation/jobs/missing/events",
    ]:
        assert client.get(route).status_code == 404
    for query in [{"offset": -1}, {"limit": 0}, {"limit": 1001}]:
        assert client.get("/api/preparation/jobs", params=query).status_code == 422


def test_catalog_lists_metadata_without_decoding_calibration_or_maps(workspace_root, monkeypatch):
    from etsy_listings.core.workspace.calibration import CalibrationStore

    from tests.support.marigold import marigold_template

    workspace = marigold_template(workspace_root, name="prepared-shirt")

    def unexpected_decode(*args, **kwargs):
        raise AssertionError("Catalog must not inspect full calibration pixels")

    monkeypatch.setattr(CalibrationStore, "photo_identity", unexpected_decode)
    client = TestClient(create_app(workspace))
    response = client.get("/api/templates")
    assert response.status_code == 200
    rows = {row["name"]: row for row in response.json()}
    assert rows["prepared-shirt"]["renderer"] == "marigold"
    assert rows["prepared-shirt"]["maps"] is None
    assert rows["flat-lay-01"]["maps"]["state"] == "not_required"


def test_catching_up_queues_coverage_for_prepared_templates(workspace_root: Path) -> None:
    from tests.support.marigold import PreparationRuntime, prepare_template, small_print

    workspace = small_print(workspace_root)
    prepare_template(workspace, "tee")
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))

    queued = client.post("/api/preparation/coverage")

    assert queued.status_code == 202
    assert [(job["template"], job["kind"]) for job in queued.json()] == [("tee", "coverage")]


def test_coverage_says_when_a_prepared_template_cannot_take_positions_yet(
    workspace_root: Path,
) -> None:
    from tests.support.marigold import PreparationRuntime, prepare_template, small_print

    workspace = small_print(workspace_root)
    prepare_template(workspace, "tee")
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))

    assert client.get("/api/templates/tee/coverage").json()["ready"] is False


def test_an_unprepared_template_is_not_held_back_by_coverage(workspace_root: Path) -> None:
    from tests.support.marigold import PreparationRuntime, small_print

    workspace = small_print(workspace_root)
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))

    assert client.get("/api/templates/tee/coverage").json()["ready"] is True


def test_a_template_with_a_job_under_way_is_preparing(workspace_root: Path) -> None:
    from tests.support.marigold import PreparationRuntime, prepare_template, small_print

    workspace = small_print(workspace_root)
    prepare_template(workspace, "tee")
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))
    client.post("/api/templates/tee/coverage")

    assert client.get("/api/templates/tee/coverage").json() == {"ready": False, "preparing": True}


def test_asking_to_adjust_queues_coverage_and_answers_null_when_none_is_needed(
    workspace_root: Path,
) -> None:
    from tests.support.marigold import (
        PreparationRuntime,
        marigold_template,
        prepare_template,
        small_print,
    )

    workspace = marigold_template(workspace_root)
    prepare_template(workspace)
    small_print(workspace_root)
    prepare_template(workspace, "tee")
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))

    queued = client.post("/api/templates/tee/coverage")
    assert queued.status_code == 202
    assert (queued.json()["template"], queued.json()["kind"]) == ("tee", "coverage")
    assert client.post("/api/templates/shirt/coverage").json() is None

"""Read-only preparation status and explicit coordinator HTTP requests."""

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.workspace import Workspace
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
    assert client.get("/api/templates/colour-chart-01/mask").status_code == 400
    assert client.get("/api/templates/flat-lay-01/placements/arbitrary/mask").status_code == 400


def test_explicit_submission_reconnect_and_cancel_keep_one_durable_job(
    workspace_root: Path,
) -> None:
    from etsy_listings.core.render import load_template_config

    from tests.support.marigold import PreparationRuntime

    workspace = Workspace.discover(root_override=workspace_root)
    config = workspace.load_template_config("flat-lay-01").model_dump(mode="json")
    config["renderer"] = {"type": "marigold", "config": {}}
    workspace.save_template_config("flat-lay-01", load_template_config(config))
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

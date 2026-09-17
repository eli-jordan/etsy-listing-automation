"""The runs resource's HTTP surface (A33): payload shape, status codes, SSE
framing and ``openapi.json`` -- through a real ``TestClient``, never a fake
transport, because the thing under test *is* the wire format.

Every test opens the client as ``with TestClient(app) as client:`` rather than
constructing one bare -- that is what runs the FastAPI lifespan (startup
starts the runs executor's worker thread; shutdown joins it), and a run
created against a client that never entered its ``with`` block would sit
`queued` forever with nothing to dequeue it.

The root "done when" for this whole PR lives here:
``test_a_plan_run_streams_its_full_event_sequence`` and
``test_an_apply_run_streams_its_full_event_sequence`` are what prove a plan
run and an apply run each stream their complete event sequence through
``TestClient`` -- everything else in this file is one contract-shaped slice
of that same surface.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.clients.printify.fakes import FakeCatalogClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import copy_listing


def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


@pytest.fixture
def client(workspace_root: Path) -> Iterator[TestClient]:
    workspace = Workspace.discover(root_override=workspace_root)
    app = create_app(workspace, context_factory=_context_factory)
    with TestClient(app) as test_client:
        yield test_client


def _wait_until_terminal(
    client: TestClient, run_id: str, *, timeout: float = 15.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail: dict[str, Any] = client.get(f"/api/runs/{run_id}").json()
        if detail["phase"] in {"ready", "applied", "failed", "stale", "cancelled"}:
            return detail
        time.sleep(0.05)
    pytest.fail(f"run {run_id} never reached a terminal phase")


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """One dict per frame -- ``id``/``event`` from their own lines, ``data``
    decoded as JSON. Blank-line-separated, per the SSE wire format."""
    events = []
    for block in raw.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        frame: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            if key == "data":
                frame["data"] = json.loads(value)
            elif key in ("id", "event"):
                frame[key] = value
        events.append(frame)
    return events


# --------------------------------------------------------------------- create


def test_create_a_plan_run_returns_202_and_a_summary(client: TestClient) -> None:
    response = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]})

    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "plan"
    assert body["listings"] == [LISTING]
    assert body["phase"] == "queued"
    assert body["seen"] is False
    assert "id" in body

    _wait_until_terminal(client, body["id"])


def test_create_is_refused_409_when_the_listing_is_already_active(client: TestClient) -> None:
    first = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()

    second = client.post("/api/runs", json={"kind": "apply", "listings": [LISTING]})

    assert second.status_code == 409
    assert second.json() == {"active_run": first["id"]}

    _wait_until_terminal(client, first["id"])


# ---------------------------------------------------------------------- list


def test_list_runs_filters_by_listing(workspace_root: Path, client: TestClient) -> None:
    copy_listing(workspace_root, "second")
    a = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()
    b = client.post("/api/runs", json={"kind": "plan", "listings": ["second"]}).json()

    rows = client.get("/api/runs", params={"listing": "second"}).json()

    assert [row["id"] for row in rows] == [b["id"]]
    _wait_until_terminal(client, a["id"])
    _wait_until_terminal(client, b["id"])


def test_list_runs_for_an_untouched_listing_is_empty(client: TestClient) -> None:
    assert client.get("/api/runs", params={"listing": "never-touched"}).json() == []


# ----------------------------------------------------------------------- get


def test_get_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope").status_code == 404


def test_get_run_carries_its_events(client: TestClient) -> None:
    created = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()

    detail = _wait_until_terminal(client, created["id"])

    assert detail["events"][0]["type"] == "phase"
    assert detail["events"][0]["phase"] == "queued"
    assert any(e["type"] == "listing_planned" for e in detail["events"])


# -------------------------------------------------------------------- cancel


def test_cancel_an_apply_run_is_409(client: TestClient) -> None:
    created = client.post("/api/runs", json={"kind": "apply", "listings": [LISTING]}).json()

    response = client.delete(f"/api/runs/{created['id']}")

    assert response.status_code == 409
    _wait_until_terminal(client, created["id"])


def test_cancel_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.delete("/api/runs/nope").status_code == 404


def test_cancel_a_queued_plan_run(workspace_root: Path, client: TestClient) -> None:
    copy_listing(workspace_root, "second")
    first = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()
    second = client.post("/api/runs", json={"kind": "plan", "listings": ["second"]}).json()

    response = client.delete(f"/api/runs/{second['id']}")

    assert response.status_code == 200
    assert response.json()["phase"] == "cancelled"
    _wait_until_terminal(client, first["id"])


# ---------------------------------------------------------------------- seen


def test_mark_seen(client: TestClient) -> None:
    created = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()
    _wait_until_terminal(client, created["id"])

    response = client.post(f"/api/runs/{created['id']}/seen")

    assert response.status_code == 200
    assert response.json()["seen"] is True


def test_seen_on_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.post("/api/runs/nope/seen").status_code == 404


# ------------------------------------------------------------------------ SSE


def test_a_plan_run_streams_its_full_event_sequence(client: TestClient) -> None:
    """The root "done when" for this PR, half of it: every event a plan run
    produces, in order, through the real SSE route."""
    created = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()

    response = client.get(f"/api/runs/{created['id']}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)

    ids = [int(e["id"]) for e in events]
    assert ids == sorted(ids)
    assert ids == list(range(1, len(events) + 1))

    types = [e["event"] for e in events]
    assert types[0] == "phase"
    assert events[0]["data"]["phase"] == "queued"
    assert types[-1] == "phase"
    assert events[-1]["data"]["phase"] == "ready"
    assert "stage_checking" in types
    assert "stage_planned" in types
    assert "listing_planned" in types
    assert "preview_rendered" in types


def test_an_apply_run_streams_its_full_event_sequence(client: TestClient) -> None:
    """The root "done when", the other half: an apply run's full sequence."""
    created = client.post("/api/runs", json={"kind": "apply", "listings": [LISTING]}).json()

    response = client.get(f"/api/runs/{created['id']}/events")

    events = _parse_sse(response.text)
    types = [e["event"] for e in events]

    assert types[0] == "phase"
    assert events[0]["data"]["phase"] == "queued"
    assert types[-1] == "phase"
    assert events[-1]["data"]["phase"] == "applied"
    assert "stage_applying" in types
    assert "stage_applied" in types
    assert "progress" in types


def test_last_event_id_replays_only_what_came_after(client: TestClient) -> None:
    created = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()
    _wait_until_terminal(client, created["id"])

    full = _parse_sse(client.get(f"/api/runs/{created['id']}/events").text)
    assert len(full) > 3
    cutoff = int(full[2]["id"])

    replayed = _parse_sse(
        client.get(f"/api/runs/{created['id']}/events", headers={"Last-Event-ID": str(cutoff)}).text
    )

    assert [int(e["id"]) for e in replayed] == [int(e["id"]) for e in full if int(e["id"]) > cutoff]


def test_an_invalid_last_event_id_replays_everything(client: TestClient) -> None:
    created = client.post("/api/runs", json={"kind": "plan", "listings": [LISTING]}).json()
    _wait_until_terminal(client, created["id"])

    replayed = _parse_sse(
        client.get(
            f"/api/runs/{created['id']}/events", headers={"Last-Event-ID": "not-a-number"}
        ).text
    )

    assert replayed[0]["data"]["phase"] == "queued"


def test_streaming_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope/events").status_code == 404


# --------------------------------------------------------------------- openapi


def test_run_event_appears_in_openapi_with_every_variant(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    definitions = schema["components"]["schemas"]

    expected = {
        "PhaseEvent",
        "StageCheckingEvent",
        "StagePlannedEvent",
        "ListingPlannedEvent",
        "PreviewRenderedEvent",
        "StageApplyingEvent",
        "ProgressEvent",
        "StageAppliedEvent",
        "StageFailedEvent",
        "ListingFailedEvent",
    }
    assert expected <= definitions.keys()

    run_detail = definitions["RunDetail"]
    events_schema = run_detail["properties"]["events"]
    # A list of the discriminated union, however the schema nests it --
    # openapi's `$ref`s point at `RunEvent` or straight at its `oneOf`.
    assert "items" in events_schema

"""What the API reports while a backup's pause holds work (workspace-backup
plan, decision P4): ``waiting_for_backup`` on a deploy run, a manual AI run,
a batch row and a Prepare job submitted during the pause, and the flag
clearing once the pause ends.

Through the app the seller drives, with its lifespan running, because what
this pins is that the server builds one gate and every coordinator shares it.
The pause itself is the gate on ``app.state``, as the backup coordinator
will hold it; how each coordinator holds and releases work is its own
behaviour test's subject under ``tests/core/behaviour``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import ChainProvider, seed_prompts, seeded_market, wait_for
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.clients import FakeClients
from tests.support.marigold import PreparationRuntime, marigold_template


def _context(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    sink = {"on_event": on_event} if on_event is not None else {}
    return RunContext(workspace=workspace, catalog=FakeCatalogClient([], {}, {}), **sink)


@pytest.fixture
def client(workspace_root: Path) -> Iterator[TestClient]:
    seed_prompts(workspace_root)
    workspace = marigold_template(workspace_root)
    a_listing_template(workspace)
    provider = ChainProvider()
    app = create_app(
        workspace,
        context_factory=_context,
        seo_provider_factory=lambda _workspace, _ai: [provider],
        preparation_runtime=PreparationRuntime(),
        clients=FakeClients(etsy_market=seeded_market()).factories(),
    )
    with TestClient(app) as test_client:
        yield test_client


def _gate(client: TestClient) -> JobGate:
    gate: JobGate = client.app.state.job_gate  # type: ignore[attr-defined]  # -- TestClient.app is the ASGI app create_app returned
    return gate


def _get(client: TestClient, url: str) -> dict[str, Any]:
    response = client.get(url)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_deploy_run_submitted_during_a_pause_waits_for_backup(client: TestClient) -> None:
    _gate(client).pause()

    created = client.post(
        "/api/runs", json={"kind": "plan", "scope": "listings", "listings": [LISTING]}
    )

    assert created.status_code == 202, created.text
    assert created.json()["waiting_for_backup"] is True
    run_id = created.json()["id"]
    assert _get(client, f"/api/runs/{run_id}")["waiting_for_backup"] is True

    _gate(client).resume()
    wait_for(lambda: _get(client, f"/api/runs/{run_id}")["phase"] == "ready")
    assert _get(client, f"/api/runs/{run_id}")["waiting_for_backup"] is False


def test_a_manual_ai_run_started_during_a_pause_is_queued_waiting_for_backup(
    client: TestClient,
) -> None:
    _gate(client).pause()

    created = client.post("/api/ai/runs", json={"listing": LISTING})

    assert created.status_code == 202, created.text
    assert (created.json()["phase"], created.json()["waiting_for_backup"]) == ("queued", True)
    found = _get(client, f"/api/ai/runs?listing={LISTING}")
    assert found["waiting_for_backup"] is True

    _gate(client).resume()
    wait_for(lambda: _get(client, f"/api/ai/runs/{found['id']}")["phase"] == "done")
    assert _get(client, f"/api/ai/runs/{found['id']}")["waiting_for_backup"] is False


def test_a_batch_confirmed_during_a_pause_has_its_rows_waiting_for_backup(
    client: TestClient,
) -> None:
    _gate(client).pause()
    staged = client.post(
        "/api/staging",
        data={"listing_template": LISTING_TEMPLATE},
        files=[("files", ("night-hike-club.png", png(1), "image/png"))],
    )
    assert staged.status_code == 200, staged.text
    confirmed = client.post(f"/api/staging/{staged.json()['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    batch_id = confirmed.json()["id"]

    rows = _get(client, f"/api/batches/{batch_id}")["rows"]
    assert [(row["ai"], row["waiting_for_backup"]) for row in rows] == [("queued", True)]

    _gate(client).resume()
    wait_for(lambda: _get(client, f"/api/batches/{batch_id}")["rows"][0]["ai"] == "done")
    assert _get(client, f"/api/batches/{batch_id}")["rows"][0]["waiting_for_backup"] is False


def test_a_prepare_job_submitted_during_a_pause_waits_for_backup(client: TestClient) -> None:
    _gate(client).pause()
    revision = _get(client, "/api/templates/shirt/preparation")["config_revision"]

    created = client.post(
        "/api/preparation/jobs",
        json={"template": "shirt", "config_revision": revision, "request_id": "during"},
    )

    assert created.status_code == 202, created.text
    assert (created.json()["phase"], created.json()["waiting_for_backup"]) == ("queued", True)
    job_id = created.json()["id"]
    active = _get(client, "/api/templates/shirt/preparation")["active_job"]
    assert active["waiting_for_backup"] is True

    _gate(client).resume()
    wait_for(
        lambda: _get(client, f"/api/preparation/jobs/{job_id}")["phase"] == "completed",
        timeout=30,
    )
    assert _get(client, f"/api/preparation/jobs/{job_id}")["waiting_for_backup"] is False

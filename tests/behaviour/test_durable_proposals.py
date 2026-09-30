"""A proposal outlives the server that generated it (ADR-0049; spec, *Durable AI
proposals*; ADR-0003 as amended by ADR-0047).

Each ``TestClient`` block is one server lifetime: ``create_app`` builds a
fresh AI run registry, so nothing held in memory crosses from one to the
next. What the second server can read is only what the first left in
``.cache/proposals/``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.ui.api.app import create_app

from tests.support.ai_runs import ChainProvider, proposal_payload, seed_prompts, seeded_market
from tests.support.builders import FIXTURE_LISTING as LISTING

PROPOSAL = f"/api/listings/{LISTING}/proposal"


@contextmanager
def _server(root: Path, provider: ChainProvider) -> Iterator[TestClient]:
    market = seeded_market()
    app = create_app(
        Workspace.discover(root_override=root),
        seo_provider_factory=lambda _workspace: [provider],
        market_client_factory=lambda _workspace: market,
    )
    with TestClient(app) as client:
        yield client


def _generate(client: TestClient) -> None:
    started = client.post("/api/ai/runs", json={"listing": LISTING})
    assert started.status_code == 202, started.text
    deadline = time.monotonic() + 15
    while client.get(f"/api/ai/runs/{started.json()['id']}").json()["phase"] == "running":
        assert time.monotonic() < deadline, "the AI run never finished"
        time.sleep(0.02)


def _titled(first: str) -> str:
    payload: dict[str, Any] = json.loads(proposal_payload())
    payload["titles"][0] = first
    return json.dumps(payload)


def test_a_manual_runs_proposal_survives_a_restart(workspace_root: Path) -> None:
    seed_prompts(workspace_root)
    with _server(workspace_root, ChainProvider()) as first:
        _generate(first)
        generated_at = first.get(PROPOSAL).json()["generated_at"]
        first.patch(
            f"{PROPOSAL}/resolution", json={"generated_at": generated_at, "tags": "accepted"}
        )

    with _server(workspace_root, ChainProvider()) as second:
        assert second.get("/api/ai/runs", params={"listing": LISTING}).status_code == 404
        restored = second.get(PROPOSAL)

    assert restored.status_code == 200
    body = restored.json()
    assert body["generated_at"] == generated_at
    assert body["proposal"]["titles"][0] == "Retro Sunset Hike Tee"
    assert body["resolution"] == {"title": "pending", "tags": "accepted", "lead": "pending"}


def test_a_regenerated_proposal_replaces_the_one_before_it(workspace_root: Path) -> None:
    seed_prompts(workspace_root)
    provider = ChainProvider(answers={"seo": [_titled("First Title"), _titled("Second Title")]})
    with _server(workspace_root, provider) as first:
        _generate(first)
        before = first.get(PROPOSAL).json()
        first.patch(
            f"{PROPOSAL}/resolution",
            json={"generated_at": before["generated_at"], "title": "accepted"},
        )

    with _server(workspace_root, provider) as second:
        _generate(second)
        after = second.get(PROPOSAL).json()

    assert before["proposal"]["titles"][0] == "First Title"
    assert after["proposal"]["titles"][0] == "Second Title"
    assert after["generated_at"] != before["generated_at"]
    assert after["resolution"] == {"title": "pending", "tags": "pending", "lead": "pending"}

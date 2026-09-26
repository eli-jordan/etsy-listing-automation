"""The whole AI run over HTTP and SSE with real Etsy market research."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings import connections
from etsy_listings.ai.brief import default_brief_prompt_text
from etsy_listings.ai.market_queries import default_market_queries_prompt_text
from etsy_listings.ai.prompt import default_seo_prompt_text
from etsy_listings.ai.providers import AiProvider
from etsy_listings.market.snapshot import load as load_market_snapshot
from etsy_listings.ui.api.app import create_app
from etsy_listings.ui.api.schemas import SeoProposalResponse
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, edit_listing

pytestmark = pytest.mark.e2e


def _frames(body: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        data = json.loads(fields["data"])
        assert fields["event"] == data["type"]
        assert int(fields["id"]) == data["seq"]
        frames.append(data)
    return frames


def test_full_ai_run_drafts_brief_researches_market_and_proposes_seo(
    workspace_root: Path,
    etsy_market_workspace: Workspace,
    ai_providers: Callable[[Workspace], Sequence[AiProvider]],
) -> None:
    edit_listing(workspace_root, brief="")
    workspace = Workspace.discover(root_override=workspace_root)
    for path, content in (
        (workspace.brief_prompt_file(), default_brief_prompt_text()),
        (workspace.market_queries_prompt_file(), default_market_queries_prompt_text()),
        (workspace.seo_prompt_file(), default_seo_prompt_text()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    app = create_app(
        workspace,
        seo_provider_factory=ai_providers,
        market_client_factory=lambda _workspace: connections.etsy_market_client(
            etsy_market_workspace.root
        ),
    )

    with TestClient(app) as client:
        started = client.post(
            "/api/ai/runs", json={"listing": FIXTURE_LISTING, "draft_brief": True}
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        streamed = client.get(f"/api/ai/runs/{run_id}/events")
        assert streamed.status_code == 200, streamed.text
        assert streamed.headers["content-type"].startswith("text/event-stream")
        events = _frames(streamed.text)
        detail = client.get(f"/api/ai/runs/{run_id}").json()

    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert [(event["id"], event["state"]) for event in events if event["type"] == "step"] == [
        ("brief", "pending"),
        ("market", "pending"),
        ("seo", "pending"),
        ("brief", "active"),
        ("brief", "done"),
        ("market", "active"),
        ("market", "active"),
        ("market", "done"),
        ("seo", "active"),
        ("seo", "done"),
    ]
    milestones = [event["type"] for event in events if event["type"] != "step"]
    assert milestones == ["brief", "queries", "market", "proposal", "phase"], detail
    assert events[-1]["phase"] == "done", detail
    assert detail["phase"] == "done", detail
    assert [step["state"] for step in detail["steps"]] == ["done", "done", "done"]
    assert workspace.load_listing(FIXTURE_LISTING).brief.strip()
    assert next(event for event in events if event["type"] == "brief")["written"] is True

    snapshot = load_market_snapshot(workspace, FIXTURE_LISTING)
    assert snapshot is not None
    market_event = next(event for event in events if event["type"] == "market")
    assert market_event["snapshot"] == snapshot.model_dump(mode="json")
    assert 1 <= snapshot.scored <= 20
    proposal = next(event for event in events if event["type"] == "proposal")
    validated = SeoProposalResponse.model_validate(proposal)
    assert len(validated.titles) == 3
    assert len(validated.tags) >= 1

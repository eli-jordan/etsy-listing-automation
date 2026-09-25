"""``/api/ai/runs``'s HTTP surface (the implementation plan's *Run contract*):
status codes, payloads, SSE framing and replay, reattaching, cancelling,
and that an AI run never waits on the plan/apply worker.

``create_app`` is given the two injection seams, ``seo_provider_factory``
and ``market_client_factory``, wired to a
:class:`~tests.support.ai_runs.ChainProvider` and the in-memory Etsy market.
The chain's own step sequences are ``test_ai_runner.py``'s; this file checks
they reach the wire.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.ai.models import ProviderReadiness
from etsy_listings.clients.etsy.fakes import FakeEtsyMarketClient
from etsy_listings.clients.printify.fakes import FakeCatalogClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.ui.airuns.registry import AiRun
from etsy_listings.ui.api import airuns as airuns_api
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.layout import MARKET_QUERIES_PROMPT_FILE, PROMPTS_DIR
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import (
    DRAFTED_BRIEF,
    ChainProvider,
    seed_prompts,
    seeded_market,
    wait_for,
)
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing


def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


@contextmanager
def _client(
    root: Path, provider: ChainProvider, market: FakeEtsyMarketClient | None = None
) -> Iterator[TestClient]:
    workspace = Workspace.discover(root_override=root)
    market = market if market is not None else seeded_market()
    app = create_app(
        workspace,
        context_factory=_context_factory,
        seo_provider_factory=lambda _workspace: [provider],
        market_client_factory=lambda _workspace: market,
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def client(workspace_root: Path, provider: ChainProvider) -> Iterator[TestClient]:
    seed_prompts(workspace_root)
    with _client(workspace_root, provider) as test_client:
        yield test_client


def _start(client: TestClient, *, draft_brief: bool = False) -> dict[str, Any]:
    response = client.post("/api/ai/runs", json={"listing": LISTING, "draft_brief": draft_brief})
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def _finished(client: TestClient, run_id: str, *, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail: dict[str, Any] = client.get(f"/api/ai/runs/{run_id}").json()
        if detail["phase"] != "running":
            return detail
        time.sleep(0.02)
    pytest.fail(f"AI run {run_id} never finished")


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    frames = []
    for block in raw.strip("\n").split("\n\n"):
        frame: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            frame[key] = json.loads(value) if key == "data" else value
        frames.append(frame)
    return frames


# --------------------------------------------------------------------- POST


def test_post_starts_a_run_and_returns_202_and_its_summary(client: TestClient) -> None:
    body = _start(client)

    assert body["listing"] == LISTING
    assert body["draft_brief"] is False
    assert body["phase"] == "running"
    assert [step["id"] for step in body["steps"]] == ["brief", "market", "seo"]
    assert body["finished_at"] is None
    assert body["created_at"]

    detail = _finished(client, body["id"])
    assert detail["phase"] == "done"
    assert detail["finished_at"] is not None
    assert [step["state"] for step in detail["steps"]] == ["skipped", "done", "done"]


def test_a_second_post_while_one_is_active_is_409_naming_it(
    client: TestClient, provider: ChainProvider
) -> None:
    gate = provider.gate("queries")
    first = _start(client)

    response = client.post("/api/ai/runs", json={"listing": LISTING, "draft_brief": False})

    assert response.status_code == 409
    assert response.json() == {"active_run": first["id"], "reason": None}
    gate.set()
    _finished(client, first["id"])


def test_a_finished_run_is_replaced_by_the_next(client: TestClient) -> None:
    first = _start(client)
    _finished(client, first["id"])

    second = _start(client)

    assert client.get("/api/ai/runs", params={"listing": LISTING}).json()["id"] == second["id"]
    assert client.get(f"/api/ai/runs/{first['id']}").status_code == 404
    _finished(client, second["id"])


def test_post_for_an_unknown_listing_is_404(client: TestClient) -> None:
    response = client.post("/api/ai/runs", json={"listing": "never-saved"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("edit", "draft_brief", "reason"),
    [
        ({"design": {}}, True, "the listing has no selected design"),
        ({"brief": " "}, False, "the listing brief is empty"),
        ({"garment_profile": ""}, False, "the listing has no usable garment profile"),
        ({"garment_profile": "no-such-profile"}, True, "the listing has no usable garment profile"),
    ],
)
def test_post_refuses_with_the_readiness_reason(
    workspace_root: Path,
    client: TestClient,
    edit: dict[str, Any],
    draft_brief: bool,
    reason: str,
) -> None:
    edit_listing(workspace_root, **edit)

    response = client.post("/api/ai/runs", json={"listing": LISTING, "draft_brief": draft_brief})

    assert response.status_code == 409
    assert response.json() == {"active_run": None, "reason": reason}


def test_an_empty_brief_is_allowed_when_the_run_drafts_it(
    workspace_root: Path, client: TestClient
) -> None:
    edit_listing(workspace_root, brief="")

    detail = _finished(client, _start(client, draft_brief=True)["id"])

    assert detail["phase"] == "done"
    brief = next(e for e in detail["events"] if e["type"] == "brief")
    assert brief == {"type": "brief", "seq": brief["seq"], "text": DRAFTED_BRIEF, "written": True}
    assert client.get(f"/api/listings/{LISTING}").json()["brief"] == DRAFTED_BRIEF


def test_post_refuses_without_the_market_queries_prompt(
    workspace_root: Path, client: TestClient
) -> None:
    (workspace_root / PROMPTS_DIR / MARKET_QUERIES_PROMPT_FILE).unlink()

    response = client.post("/api/ai/runs", json={"listing": LISTING})

    assert response.status_code == 409
    assert "market-queries.md" in response.json()["reason"]


def test_post_refuses_without_the_brief_prompt_only_when_drafting(
    workspace_root: Path, client: TestClient
) -> None:
    (workspace_root / PROMPTS_DIR / "brief.md").unlink()
    edit_listing(workspace_root, brief="")

    refused = client.post("/api/ai/runs", json={"listing": LISTING, "draft_brief": True})
    assert refused.status_code == 409
    assert "brief.md" in refused.json()["reason"]

    edit_listing(workspace_root, brief="A brief the seller wrote.")
    run = _start(client, draft_brief=True)
    assert _finished(client, run["id"])["phase"] == "done"


def test_post_refuses_when_no_provider_is_ready(workspace_root: Path) -> None:
    seed_prompts(workspace_root)
    provider = ChainProvider(ready=ProviderReadiness(ready=False, reason="codex is signed out"))

    with _client(workspace_root, provider) as client:
        response = client.post("/api/ai/runs", json={"listing": LISTING})

    assert response.status_code == 409
    assert "codex is signed out" in response.json()["reason"]


# ---------------------------------------------------------------------- GET


def test_get_by_listing_reattaches_to_the_current_run(
    client: TestClient, provider: ChainProvider
) -> None:
    gate = provider.gate("seo")
    run = _start(client)
    wait_for(lambda: provider.started["seo"].is_set())

    found = client.get("/api/ai/runs", params={"listing": LISTING})

    assert found.status_code == 200
    body = found.json()
    assert body["id"] == run["id"]
    assert body["phase"] == "running"
    assert [step["state"] for step in body["steps"]] == ["skipped", "done", "active"]
    gate.set()
    _finished(client, run["id"])


def test_get_by_listing_is_404_without_a_run(client: TestClient) -> None:
    assert client.get("/api/ai/runs", params={"listing": LISTING}).status_code == 404


def test_deleting_the_listing_forgets_its_finished_run(client: TestClient) -> None:
    _finished(client, _start(client)["id"])

    assert client.delete(f"/api/listings/{LISTING}").status_code == 204

    assert client.get("/api/ai/runs", params={"listing": LISTING}).status_code == 404


def test_renaming_the_listing_forgets_the_finished_run_under_the_old_name(
    client: TestClient,
) -> None:
    _finished(client, _start(client)["id"])

    renamed = client.post(f"/api/listings/{LISTING}/rename", json={"new_name": "renamed"})

    assert renamed.status_code == 200
    assert client.get("/api/ai/runs", params={"listing": LISTING}).status_code == 404


def test_get_an_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/ai/runs/nope").status_code == 404
    assert client.get("/api/ai/runs/nope/events").status_code == 404
    assert client.delete("/api/ai/runs/nope").status_code == 404


def test_the_detail_carries_every_event_type(client: TestClient) -> None:
    detail = _finished(client, _start(client)["id"])

    types = [event["type"] for event in detail["events"]]
    assert set(types) == {"step", "queries", "market", "proposal", "phase"}
    assert [event["seq"] for event in detail["events"]] == list(range(1, len(types) + 1))
    proposal = next(e for e in detail["events"] if e["type"] == "proposal")
    assert {"titles", "tags", "description_leads", "snapshot", "expires_at"} <= set(proposal)
    kept_for = datetime.fromisoformat(proposal["expires_at"]) - datetime.fromisoformat(
        proposal["generated_at"]
    )
    assert kept_for == timedelta(days=1)
    market = next(e for e in detail["events"] if e["type"] == "market")
    assert market["snapshot"]["scored"] == 3
    assert detail["events"][-1] == {
        "type": "phase",
        "seq": len(types),
        "phase": "done",
        "message": None,
    }


# ---------------------------------------------------------------------- SSE


def test_the_stream_frames_every_event_and_ends_with_the_phase(client: TestClient) -> None:
    run = _start(client)
    detail = _finished(client, run["id"])

    response = client.get(f"/api/ai/runs/{run['id']}/events")

    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _parse_sse(response.text)
    assert [int(frame["id"]) for frame in frames] == list(range(1, len(frames) + 1))
    assert [frame["event"] for frame in frames] == [e["type"] for e in detail["events"]]
    assert [frame["data"] for frame in frames] == detail["events"]
    assert frames[-1]["data"]["phase"] == "done"


def test_the_stream_replays_only_what_came_after_last_event_id(client: TestClient) -> None:
    run = _start(client)
    _finished(client, run["id"])
    everything = _parse_sse(client.get(f"/api/ai/runs/{run['id']}/events").text)

    replayed = _parse_sse(
        client.get(f"/api/ai/runs/{run['id']}/events", headers={"Last-Event-ID": "4"}).text
    )

    assert replayed == everything[4:]
    garbage = client.get(f"/api/ai/runs/{run['id']}/events", headers={"Last-Event-ID": "x"})
    assert _parse_sse(garbage.text) == everything


def test_closing_the_stream_does_not_cancel_the_run(
    workspace_root: Path, provider: ChainProvider
) -> None:
    """The browser leaving is the stream's generator seeing a disconnect;
    the run goes on."""
    seed_prompts(workspace_root)
    gate = provider.gate("seo")
    with _client(workspace_root, provider) as client:
        run_id = _start(client)["id"]
        run = client.app.state.ai_run_registry.get(run_id)  # type: ignore[attr-defined]
        assert isinstance(run, AiRun)

        wait_for(lambda: provider.started["seo"].is_set())

        class Leaving:
            """Connected for the first poll, gone from the second."""

            polls = 0

            async def is_disconnected(self) -> bool:
                self.polls += 1
                return self.polls > 1

        async def read_until_gone() -> list[bytes]:
            return [frame async for frame in airuns_api.sse_events(Leaving(), run, 0)]  # type: ignore[arg-type]

        # Its own thread: another test layer (Playwright) may leave this
        # thread with a running event loop, and asyncio.run refuses that.
        with ThreadPoolExecutor(1) as pool:
            frames = pool.submit(asyncio.run, read_until_gone()).result(timeout=15)

        assert frames[0].startswith(b"id: 1\n")
        assert run.phase == "running"
        assert not run.cancel_event.is_set()
        gate.set()

        assert _finished(client, run_id)["phase"] == "done"
        assert not run.cancel_event.is_set()


# ------------------------------------------------------------------- DELETE


def test_delete_cancels_a_running_run(client: TestClient, provider: ChainProvider) -> None:
    provider.gate("queries")
    run = _start(client)
    wait_for(lambda: provider.started["queries"].is_set())

    response = client.delete(f"/api/ai/runs/{run['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == run["id"]
    detail = _finished(client, run["id"])
    assert detail["phase"] == "cancelled"
    assert provider.cancelled == ["queries"]
    assert "proposal" not in [event["type"] for event in detail["events"]]


def test_delete_on_a_finished_run_is_409(client: TestClient) -> None:
    run = _start(client)
    _finished(client, run["id"])

    assert client.delete(f"/api/ai/runs/{run['id']}").status_code == 409


# --------------------------------------------------------- beside plan/apply


def test_a_plan_run_finishes_while_an_ai_run_is_in_flight(
    client: TestClient, provider: ChainProvider
) -> None:
    gate = provider.gate("seo")
    ai_run = _start(client)
    wait_for(lambda: provider.started["seo"].is_set())

    plan = client.post(
        "/api/runs", json={"kind": "plan", "scope": "listings", "listings": [LISTING]}
    )
    assert plan.status_code == 202
    deadline = time.monotonic() + 15
    while client.get(f"/api/runs/{plan.json()['id']}").json()["phase"] != "ready":
        assert time.monotonic() < deadline, "the plan run waited on the AI run"
        time.sleep(0.02)

    assert client.get(f"/api/ai/runs/{ai_run['id']}").json()["phase"] == "running"
    gate.set()
    assert _finished(client, ai_run["id"])["phase"] == "done"


def test_leaving_the_app_cancels_active_runs(workspace_root: Path, provider: ChainProvider) -> None:
    seed_prompts(workspace_root)
    provider.gate("queries")
    with _client(workspace_root, provider) as client:
        run_id = _start(client)["id"]
        wait_for(lambda: provider.started["queries"].is_set())
        run = client.app.state.ai_run_registry.get(run_id)  # type: ignore[attr-defined]

    assert run.phase == "cancelled"
    assert provider.cancelled == ["queries"]


def test_the_run_contract_is_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    assert set(paths["/api/ai/runs"]) == {"get", "post"}
    assert set(paths["/api/ai/runs/{run_id}"]) == {"get", "delete"}
    assert "get" in paths["/api/ai/runs/{run_id}/events"]
    assert "409" in paths["/api/ai/runs"]["post"]["responses"]
    events = schema["components"]["schemas"]["AiRunDetail"]["properties"]["events"]["items"]
    mapping = events["discriminator"]["mapping"]
    assert set(mapping) == {"step", "brief", "queries", "market", "proposal", "phase"}

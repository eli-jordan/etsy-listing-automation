"""The batch AI queue (batch plan PR 4; spec *Batch AI queue*; ADR-0048): every
created row drafts its brief, researches the market and gets a proposal, a
limited number at a time across every batch, round-robin between batches.

Every test drives a real :class:`~etsy_listings.core.application.ai.batch_queue.BatchQueue`
over a real :class:`~etsy_listings.core.application.ai.runner.AiRunner`, the fixture
workspace, a :class:`~tests.support.ai_runs.ChainProvider` and the
in-memory Etsy market. What the tests read back is what the batch summary
reads: the batch record's rows, the listing files and the cached proposal.
A run is held at a step with the provider's gates, and the queue's
dispatcher is waited for with :meth:`BatchQueue.wait_idle`, never a sleep.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry
from etsy_listings.core.application.ai.runner import AiRunner
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import (
    Batch,
    BatchRow,
    BatchStore,
    StagingStore,
    confirm,
    stage_pngs,
)
from etsy_listings.core.clients.etsy.fakes import FakeEtsyMarketClient
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import TODAY, ChainProvider, Task, seed_prompts, seeded_market, wait_for
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png, uploads
from tests.support.builders import edit_listing

CREATED = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Queue:
    """A batch queue over the fixture workspace, and everything under it."""

    def __init__(self, root: Path, provider: ChainProvider, market: FakeEtsyMarketClient) -> None:
        self.workspace = Workspace.discover(root_override=root)
        self.provider = provider
        self.market = market
        self.clock = Clock()
        self.registry = AiRunRegistry()
        self.locks = WorkspaceLocks()
        self.proposals = ProposalStore(self.workspace)
        self.runner = AiRunner(
            workspace=self.workspace,
            registry=self.registry,
            locks=self.locks,
            providers=lambda _workspace: [provider],
            market_client=lambda _workspace: market,
            proposals=self.proposals,
            now=lambda: TODAY,
            monotonic=self.clock,
            watch_interval=0.01,
        )
        self.staging = StagingStore(self.workspace)
        self.batches = BatchStore(self.workspace)
        self.queue = BatchQueue(
            workspace=self.workspace,
            batches=self.batches,
            registry=self.registry,
            runner=self.runner,
        )

    def confirm(self, *designs: tuple[str, bytes], at: datetime = CREATED) -> Batch:
        session = stage_pngs(
            self.workspace, self.staging, LISTING_TEMPLATE, uploads(*designs), now=at
        )
        batch = confirm(
            self.workspace, self.staging, self.batches, session.id, lock=self.locks.listing, now=at
        )
        self.queue.wake()
        return batch

    def states(self, batch: Batch) -> list[str | None]:
        loaded = self.batches.load(batch.id)
        assert loaded is not None
        return [row.ai for row in loaded.rows]

    def row(self, batch: Batch, index: int) -> BatchRow:
        loaded = self.batches.load(batch.id)
        assert loaded is not None
        return loaded.rows[index]

    def settle(self, batch: Batch, *states: str) -> None:
        wait_for(lambda: self.states(batch) == list(states))

    def last_prompt(self, task: Task) -> str:
        calls = zip(self.provider.tasks, self.provider.calls, strict=True)
        return [t for t, kind in calls if kind == task][-1].prompt_text

    def idle(self) -> None:
        assert self.queue.wait_idle(timeout=15)

    def batch_runs(self) -> list[str]:
        """The listings whose batch runs are running now."""
        return sorted(run.listing for run in self.registry.active() if run.origin == "batch")

    def concurrency(self, limit: int) -> None:
        self.workspace.settings_file().write_text(
            f"batch_ai:\n  concurrency: {limit}\n", encoding="utf-8"
        )


def _designs(*names: str, seed: int = 1) -> list[tuple[str, bytes]]:
    return [(f"{name}.png", png(seed + i)) for i, name in enumerate(names)]


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def q(workspace_root: Path, provider: ChainProvider) -> Iterator[Queue]:
    seed_prompts(workspace_root)
    queue = Queue(workspace_root, provider, seeded_market())
    a_listing_template(queue.workspace)
    yield queue
    queue.queue.stop()
    queue.runner.shutdown()


# -------------------------------------------------------------- scheduling


def test_concurrency_one_drafts_the_rows_strictly_one_at_a_time(q: Queue) -> None:
    alongside: list[int] = []
    q.provider.during["brief"] = lambda: alongside.append(len(q.batch_runs()))
    gate = q.provider.gate("brief")
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail", "lake-loop"))
    assert q.states(batch) == ["queued", "queued", "queued"]

    q.queue.start()
    q.idle()

    assert q.batch_runs() == ["night-hike-club"]
    assert q.states(batch) == ["running", "queued", "queued"]
    gate.set()
    q.settle(batch, "done", "done", "done")
    assert alongside == [1, 1, 1]


def test_concurrency_two_drafts_two_rows_at_once(q: Queue) -> None:
    q.concurrency(2)
    gate = q.provider.gate("brief")
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail", "lake-loop"))

    q.queue.start()
    q.idle()

    assert q.batch_runs() == ["cedar-trail", "night-hike-club"]
    assert q.states(batch) == ["running", "running", "queued"]
    gate.set()
    q.settle(batch, "done", "done", "done")


def test_two_batches_are_served_round_robin_oldest_first(q: Queue) -> None:
    started: list[str] = []
    q.provider.during["brief"] = lambda: started.extend(q.batch_runs())
    first = q.confirm(*_designs("a-one", "a-two"), at=CREATED)
    second = q.confirm(*_designs("b-one", "b-two", seed=10), at=CREATED + timedelta(minutes=1))

    q.queue.start()

    q.settle(first, "done", "done")
    q.settle(second, "done", "done")
    assert started == ["a-one", "b-one", "a-two", "b-two"]


def test_a_manual_run_does_not_count_against_the_limit_and_its_listing_waits(
    q: Queue,
) -> None:
    """Manual runs are outside the batch limit, and a row whose listing a
    manual run holds is skipped until that run ends."""
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail"))
    gate = q.provider.gate("queries")
    manual = q.registry.create("night-hike-club", draft_brief=False)
    assert isinstance(manual, AiRun)

    q.queue.start()
    q.idle()

    assert q.batch_runs() == ["cedar-trail"]
    assert q.states(batch) == ["queued", "running"]
    q.runner.start(manual)
    gate.set()
    q.settle(batch, "done", "done")


# ---------------------------------------------------------------- failures


def test_a_failed_row_keeps_its_brief_and_later_rows_carry_on(q: Queue) -> None:
    # The first row's query extraction answers garbage twice (the answer
    # and its one repair), so its market step fails after the brief.
    q.provider.answers["queries"] = ["not json", "still not json"]
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail"))

    q.queue.start()

    q.settle(batch, "failed", "done")
    row = q.row(batch, 0)
    assert row.ai_error is not None
    assert [(s.id, s.state) for s in row.ai_steps] == [
        ("brief", "done"),
        ("market", "failed"),
        ("seo", "pending"),
    ]
    assert q.workspace.load_listing("night-hike-club").brief != ""
    assert q.proposals.load("night-hike-club") is None
    assert q.proposals.load("cedar-trail") is not None


def test_retry_keeps_the_saved_brief_with_the_seller_s_edit_and_reruns_the_rest(
    q: Queue,
) -> None:
    q.provider.answers["queries"] = ["not json", "still not json"]
    batch = q.confirm(*_designs("night-hike-club"))
    q.queue.start()
    q.settle(batch, "failed")
    edited = "Night sky over the trail; the seller's words."
    edit_listing(q.workspace.root, "night-hike-club", brief=edited)
    briefs = q.provider.count("brief")

    q.queue.retry(batch.id)

    q.settle(batch, "done")
    assert q.provider.count("brief") == briefs
    assert q.workspace.load_listing("night-hike-club").brief == edited
    assert edited in q.last_prompt("queries")
    record = q.proposals.load("night-hike-club")
    assert record is not None
    assert record.origin == "batch"


def test_a_brief_the_seller_wrote_before_the_row_s_turn_is_kept_and_used(q: Queue) -> None:
    gate = q.provider.gate("brief")
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail"))
    q.queue.start()
    q.idle()
    theirs = "Cedar trees in fog; the text reads CEDAR TRAIL."
    edit_listing(q.workspace.root, "cedar-trail", brief=theirs)

    gate.set()

    q.settle(batch, "done", "done")
    assert q.provider.count("brief") == 1
    assert q.workspace.load_listing("cedar-trail").brief == theirs
    assert theirs in q.last_prompt("queries")


def test_a_run_that_outlives_the_limit_becomes_a_failed_row(q: Queue) -> None:
    q.provider.gate("seo")
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail"))
    q.queue.start()
    wait_for(lambda: q.provider.started["seo"].is_set())

    q.clock.now = 180.0

    wait_for(lambda: q.states(batch)[0] == "failed")
    row = q.row(batch, 0)
    assert row.ai_error is not None
    assert "3 minutes" in row.ai_error


# ---------------------------------------------------- cancel and resume


def test_cancel_stops_the_running_row_and_leaves_the_queued_ones_stopped(q: Queue) -> None:
    gate = q.provider.gate("brief")
    batch = q.confirm(*_designs("night-hike-club", "cedar-trail", "lake-loop"))
    q.queue.start()
    q.idle()

    q.queue.cancel(batch.id)

    q.settle(batch, "cancelled", "stopped", "stopped")
    q.idle()
    assert q.batch_runs() == []
    assert q.provider.cancelled == ["brief"]

    gate.set()
    q.queue.resume(batch.id)

    q.settle(batch, "done", "done", "done")
    assert all(q.proposals.load(name) for name in ("night-hike-club", "cedar-trail", "lake-loop"))


# ----------------------------------------------------------------- restart


def test_a_row_running_when_the_server_stops_reruns_after_a_restart(
    workspace_root: Path,
) -> None:
    """A run does not survive its server, so the row it left ``running``
    is queued again on the next start, and reruns to one listing and one
    proposal (spec, *Scheduling*; ADR-0048)."""
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    market = seeded_market()
    stopping = ChainProvider()
    stopping.gate("seo")

    def app(provider: ChainProvider) -> TestClient:
        return TestClient(
            create_app(
                workspace,
                seo_provider_factory=lambda _workspace: [provider],
                market_client_factory=lambda _workspace: market,
            )
        )

    with app(stopping) as client:
        staged = client.post(
            "/api/staging",
            data={"listing_template": LISTING_TEMPLATE},
            files=[("files", ("night-hike-club.png", png(1), "image/png"))],
        ).json()
        batch_id = client.post(f"/api/staging/{staged['id']}/confirm").json()["id"]
        wait_for(lambda: stopping.started["seo"].is_set())
    assert stopping.cancelled == ["seo"]
    stored = BatchStore(workspace).load(batch_id)
    assert stored is not None
    assert [row.ai for row in stored.rows] == ["running"]

    with app(ChainProvider()) as client:
        wait_for(lambda: client.get(f"/api/batches/{batch_id}").json()["rows"][0]["ai"] == "done")

    assert [n for n in workspace.listing_names() if n != "take-a-hike"] == ["night-hike-club"]
    assert workspace.batch_ids() == [batch_id]
    record = ProposalStore(workspace).load("night-hike-club")
    assert record is not None
    assert record.origin == "batch"

"""``core/application/ai/coordinator.py``: AI coordination called directly --
no FastAPI, no TestClient (module-structure plan, PR 9).

One active run per listing, the refusals a manual run meets (an unsaved or
unready listing, a pending batch row, a deploy holding the listing), the
deploy-to-AI handoff (ADR-0050), and the coordinator's lifetime: built
without a thread, started with interrupted rows returned to the queue, and
stopped so that nothing new starts while active runs are cancelled
(ADR-0048). The HTTP mapping of each answer is
``tests/contract/test_ai_runs_api.py``'s and ``test_ai_seo_api.py``'s.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.ai.registry import AiRun, Conflict
from etsy_listings.core.application.refusals import (
    AiNotReady,
    ListingDeploying,
    ListingDraftingInBatch,
    ListingMissing,
)
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import Batch, BatchStore, StagingStore, confirm, stage_pngs
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import (
    ChainProvider,
    seed_prompts,
    seeded_market,
    wait_for,
    wait_until_finished,
)
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png, uploads
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    a_listing_template(workspace)
    return workspace


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def batches(workspace: Workspace) -> BatchStore:
    return BatchStore(workspace)


@pytest.fixture
def ai(
    workspace: Workspace, provider: ChainProvider, batches: BatchStore
) -> Iterator[AiCoordinator]:
    market = seeded_market()
    coordinator = AiCoordinator(
        workspace,
        locks=WorkspaceLocks(),
        proposals=ProposalStore(workspace),
        batches=batches,
        providers=lambda _workspace: [provider],
        market_client=lambda _workspace: market,
    )
    yield coordinator
    coordinator.stop()


def _batch(workspace: Workspace, batches: BatchStore, *names: str) -> Batch:
    """A confirmed batch whose rows are queued, created without waking any
    queue -- what a confirm leaves on disk."""
    staging = StagingStore(workspace)
    files = [(f"{name}.png", png(i + 1)) for i, name in enumerate(names)]
    session = stage_pngs(workspace, staging, LISTING_TEMPLATE, uploads(*files))
    return confirm(workspace, staging, batches, session.id, lock=WorkspaceLocks().listing)


def _states(batches: BatchStore, batch: Batch) -> list[str | None]:
    loaded = batches.load(batch.id)
    assert loaded is not None
    return [row.ai for row in loaded.rows]


def _started(result: AiRun | Conflict) -> AiRun:
    assert isinstance(result, AiRun), result
    return result


# ----------------------------------------------------------- manual runs


def test_constructing_the_coordinator_starts_no_thread(
    workspace: Workspace, provider: ChainProvider, batches: BatchStore
) -> None:
    before = {thread.ident for thread in threading.enumerate()}

    AiCoordinator(
        workspace,
        locks=WorkspaceLocks(),
        proposals=ProposalStore(workspace),
        batches=batches,
        providers=lambda _workspace: [provider],
        market_client=lambda _workspace: None,
    )

    assert {thread.ident for thread in threading.enumerate()} == before


def test_a_manual_run_drafts_researches_and_caches_its_proposal(
    ai: AiCoordinator, workspace: Workspace
) -> None:
    run = wait_until_finished(_started(ai.start_run(LISTING, draft_brief=False)))

    assert (run.phase, run.origin) == ("done", "manual")
    assert ProposalStore(workspace).load(LISTING) is not None


def test_a_second_run_for_an_active_listing_names_the_first(
    ai: AiCoordinator, provider: ChainProvider
) -> None:
    gate = provider.gate("queries")
    first = _started(ai.start_run(LISTING, draft_brief=False))

    again = ai.start_run(LISTING, draft_brief=False)

    assert again == Conflict(active_run=first.id)
    gate.set()
    wait_until_finished(first)
    assert _started(ai.start_run(LISTING, draft_brief=False)).id != first.id


def test_an_unsaved_listing_is_refused(ai: AiCoordinator) -> None:
    with pytest.raises(ListingMissing):
        ai.start_run("never-saved", draft_brief=False)


def test_an_unready_listing_is_refused_with_the_rule_that_failed(
    ai: AiCoordinator, workspace_root: Path
) -> None:
    edit_listing(workspace_root, brief="")

    with pytest.raises(AiNotReady) as refused:
        ai.start_run(LISTING, draft_brief=False)

    assert str(refused.value) == "the listing brief is empty"
    assert ai.blocked(LISTING) is None, "the button drafts an empty brief"
    assert ai.registry.latest(LISTING) is None


# ---------------------------------------------------------------- batches


def test_a_pending_batch_row_owns_its_listing_s_ai(
    ai: AiCoordinator, workspace: Workspace, batches: BatchStore
) -> None:
    """ADR-0048: two runs must never own one listing, even before the queue
    has started the row's run."""
    _batch(workspace, batches, "night-hike-club")

    with pytest.raises(ListingDraftingInBatch):
        ai.start_run("night-hike-club", draft_brief=True)

    assert isinstance(ai.blocked("night-hike-club"), ListingDraftingInBatch)
    assert ai.blocked(LISTING) is None


def test_start_returns_interrupted_rows_to_the_queue_and_drafts_them(
    ai: AiCoordinator, workspace: Workspace, batches: BatchStore
) -> None:
    """A run does not survive its server, so a row a previous one left
    ``running`` is queued again and reruns (ADR-0048)."""
    batch = _batch(workspace, batches, "night-hike-club")
    with batches.lock(batch.id):
        loaded = batches.load(batch.id)
        assert loaded is not None
        loaded.rows[0] = loaded.rows[0].model_copy(update={"ai": "running"})
        batches.save(loaded)

    ai.start()

    wait_for(lambda: _states(batches, batch) == ["done"])
    record = ProposalStore(workspace).load("night-hike-club")
    assert record is not None and record.origin == "batch"


def test_stop_cancels_active_runs_and_starts_nothing_more(
    ai: AiCoordinator, workspace: Workspace, batches: BatchStore, provider: ChainProvider
) -> None:
    """Shutdown order (ADR-0048): the queue stops before the runs are
    cancelled, so a run ending on the way out frees no slot for the next
    row. The cancelled row stays ``running``, for the next start to rerun."""
    provider.gate("brief")
    batch = _batch(workspace, batches, "night-hike-club", "cedar-trail")
    # A slow listener: a run ending gives a dispatcher still running the
    # time to answer the wake its ending sent, before the stop returns.
    ai.registry.subscribe(lambda _run: ai.queue.wait_idle(timeout=0.5))
    ai.start()
    wait_for(lambda: provider.started["brief"].is_set())

    ai.stop()

    assert provider.cancelled == ["brief"], "the provider call was killed"
    assert provider.count("brief") == 1
    assert _states(batches, batch) == ["running", "queued"]
    assert ai.registry.active() == []


# ---------------------------------------------------------------- deploys


def test_a_deploy_stops_the_listing_s_run_and_refuses_new_ones_until_it_ends(
    ai: AiCoordinator, provider: ChainProvider
) -> None:
    """ADR-0050: the run is stopped and awaited before the deploy reads the
    listing; while the deploy holds it, a new run is refused."""
    provider.gate("queries")
    run = _started(ai.start_run(LISTING, draft_brief=False))
    wait_for(lambda: provider.started["queries"].is_set())

    with ai.yield_to_deploy([LISTING]):
        assert run.phase == "cancelled"
        assert provider.cancelled == ["queries"]
        with pytest.raises(ListingDeploying):
            ai.start_run(LISTING, draft_brief=False)
        assert isinstance(ai.blocked(LISTING), ListingDeploying)

    assert ai.blocked(LISTING) is None
    assert _started(ai.start_run(LISTING, draft_brief=False)).id != run.id


def test_a_deploy_cancels_the_listing_s_queued_rows_for_good(
    ai: AiCoordinator, workspace: Workspace, batches: BatchStore
) -> None:
    """``cancelled_by_deploy`` is not resumed: no proposal lands on a
    listing after its deploy unless the seller retries the row."""
    batch = _batch(workspace, batches, "night-hike-club")

    with ai.yield_to_deploy(["night-hike-club"]):
        assert _states(batches, batch) == ["cancelled_by_deploy"]
    ai.queue.resume(batch.id)

    assert _states(batches, batch) == ["cancelled_by_deploy"]

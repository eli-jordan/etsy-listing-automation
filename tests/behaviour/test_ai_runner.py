"""One AI run end to end on its own thread (market-seo.md, *The chain*,
*Failures* and *AI runs*; implementation plan, PR 5): brief, query
extraction and market search, then the proposal.

Every test drives :class:`~etsy_listings.ui.airuns.runner.AiRunner` against
the fixture workspace, a :class:`~tests.support.ai_runs.ChainProvider` and
the in-memory Etsy market, and reads the run back through its events and
steps -- the same things the SSE stream and the indicator read. The step
sequences are the *Scenarios* table in ``ui-market-seo-interactions.md``.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml

from etsy_listings.ai.errors import SeoTryAgainError
from etsy_listings.clients.etsy.fakes import FakeEtsyMarketClient, server_error
from etsy_listings.errors import INTERNAL_ERROR_MESSAGE
from etsy_listings.market import snapshot as market_snapshot
from etsy_listings.market.block import MARKET_BEGIN
from etsy_listings.ui.airuns.events import AiStepEvent, StepId
from etsy_listings.ui.airuns.registry import AiRun, AiRunRegistry
from etsy_listings.ui.airuns.runner import RUN_LIMIT_SECONDS, TIMEOUT_MESSAGE, AiRunner
from etsy_listings.ui.workspace_locks import WorkspaceLocks
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import (
    DRAFTED_BRIEF,
    QUERIES,
    TODAY,
    ChainProvider,
    seed_prompts,
    seeded_market,
    wait_for,
    wait_until_finished,
)
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing, set_etsy_shop_id

SELLER_BRIEF = "The seller's own words about the sunset design."


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Chain:
    """A runner over the fixture workspace, and what it was given."""

    def __init__(
        self,
        root: Path,
        provider: ChainProvider,
        market: FakeEtsyMarketClient | None,
    ) -> None:
        self.workspace = Workspace.discover(root_override=root)
        self.registry = AiRunRegistry()
        self.locks = WorkspaceLocks()
        self.provider = provider
        self.market = market
        self.clock = Clock()
        self.runner = AiRunner(
            workspace=self.workspace,
            registry=self.registry,
            locks=self.locks,
            providers=lambda _workspace: [provider],
            market_client=lambda _workspace: market,
            now=lambda: TODAY,
            monotonic=self.clock,
            watch_interval=0.01,
        )

    def start(self, *, draft_brief: bool) -> AiRun:
        run = self.registry.create(LISTING, draft_brief=draft_brief)
        assert isinstance(run, AiRun)
        self.runner.start(run)
        return run

    def run(self, *, draft_brief: bool) -> AiRun:
        return wait_until_finished(self.start(draft_brief=draft_brief))

    def saved_brief(self) -> str:
        return self.workspace.load_listing(LISTING).brief


@pytest.fixture
def provider() -> ChainProvider:
    return ChainProvider()


@pytest.fixture
def chain(workspace_root: Path, provider: ChainProvider) -> Iterator[Chain]:
    seed_prompts(workspace_root)
    chain = Chain(workspace_root, provider, seeded_market())
    yield chain
    chain.runner.shutdown()


def _history(run: AiRun, step: StepId) -> list[str]:
    return [e.state for e in run.events if isinstance(e, AiStepEvent) and e.id == step]


def _types(run: AiRun) -> list[str]:
    return [event.type for event in run.events]


def _detail(run: AiRun, step: StepId) -> str | None:
    return next(s.detail for s in run.steps if s.id == step)


def _state(run: AiRun) -> dict[str, str]:
    return {s.id: s.state for s in run.steps}


def _becomes(run: AiRun, predicate: Callable[[], bool], *, timeout: float) -> bool:
    with run.condition:
        return run.condition.wait_for(predicate, timeout=timeout)


# ---------------------------------------------------------------- scenarios


def test_the_auto_chain_drafts_the_brief_then_researches_then_proposes(chain: Chain) -> None:
    edit_listing(chain.workspace.root, brief="")

    run = chain.run(draft_brief=True)

    assert _history(run, "brief") == ["pending", "active", "done"]
    assert _history(run, "market") == ["pending", "active", "active", "done"]
    assert _history(run, "seo") == ["pending", "active", "done"]
    assert _types(run)[:3] == ["step", "step", "step"]
    assert [t for t in _types(run) if t != "step"] == [
        "brief",
        "queries",
        "market",
        "proposal",
        "phase",
    ]
    assert run.phase == "done"
    assert chain.provider.calls == ["brief", "queries", "seo"]
    assert chain.saved_brief() == DRAFTED_BRIEF
    assert _detail(run, "brief") == "Drafted from take-a-hike.png"
    assert _detail(run, "market") == "3 listings scored, from 3 found"
    assert _detail(run, "seo") == "3 titles, 20 tags, 3 leads to review"


def test_the_events_carry_the_brief_queries_snapshot_and_proposal(chain: Chain) -> None:
    edit_listing(chain.workspace.root, brief="")

    run = chain.run(draft_brief=True)

    by_type = {event.type: event for event in run.events}
    brief = by_type["brief"]
    assert brief.model_dump(include={"text", "written"}) == {"text": DRAFTED_BRIEF, "written": True}
    assert by_type["queries"].model_dump()["queries"] == list(QUERIES)
    market = by_type["market"].model_dump()["snapshot"]
    assert market["scored"] == 3
    assert market["searched_at"] == TODAY
    saved = market_snapshot.load(chain.workspace, LISTING)
    assert saved is not None
    assert saved.model_dump() == market
    proposal = by_type["proposal"].model_dump()
    assert proposal["titles"][0] == "Retro Sunset Hike Tee"
    assert proposal["snapshot"]["brief"] == DRAFTED_BRIEF


def test_extraction_and_the_proposal_see_the_drafted_brief_and_the_market(chain: Chain) -> None:
    edit_listing(chain.workspace.root, brief="")

    chain.run(draft_brief=True)

    queries_prompt = chain.provider.task("queries").prompt_text
    assert DRAFTED_BRIEF in queries_prompt
    assert "Unisex Garment-Dyed T-shirt" in queries_prompt
    seo_prompt = chain.provider.task("seo").prompt_text
    assert MARKET_BEGIN in seo_prompt
    assert "Retro Sunset Hiking Shirt Tee" in seo_prompt
    assert chain.provider.task("seo").design_image.name == "take-a-hike.png"


def test_unconventional_design_keys_send_the_same_image_whatever_their_order(
    chain: Chain,
) -> None:
    root = chain.workspace.root
    (root / "designs" / "alternate.png").write_bytes(b"alternate")
    primary, secondary = "../../designs/take-a-hike.png", "../../designs/alternate.png"

    edit_listing(root, design={"z": secondary, "a": primary})
    chain.run(draft_brief=False)
    edit_listing(root, design={"a": primary, "z": secondary})
    chain.run(draft_brief=False)

    images = [
        t.design_image
        for t, k in zip(chain.provider.tasks, chain.provider.calls, strict=True)
        if k == "seo"
    ]
    assert [image.name for image in images] == ["take-a-hike.png", "take-a-hike.png"]


def test_the_ai_mode_button_skips_the_brief(chain: Chain) -> None:
    run = chain.run(draft_brief=False)

    assert _history(run, "brief") == ["skipped"]
    assert _detail(run, "brief") == "You wrote the brief, so it was kept"
    assert _history(run, "market") == ["pending", "active", "active", "done"]
    assert _history(run, "seo") == ["pending", "active", "done"]
    assert "brief" not in chain.provider.calls
    assert run.phase == "done"


def test_the_auto_chain_skips_a_brief_the_seller_wrote_before_it_fired(chain: Chain) -> None:
    run = chain.run(draft_brief=True)

    assert _history(run, "brief") == ["skipped"]
    assert chain.provider.calls == ["queries", "seo"]
    assert "Retro 70s sunset mountain scene" in chain.saved_brief()


def test_no_comparable_listings_is_a_warning_and_the_proposal_goes_ahead(
    workspace_root: Path, provider: ChainProvider
) -> None:
    seed_prompts(workspace_root)
    chain = Chain(workspace_root, provider, seeded_market(comparable=False))

    run = chain.run(draft_brief=False)

    assert _history(run, "market") == ["pending", "active", "active", "warning"]
    assert _detail(run, "market") == "No comparable listings found, even with filters relaxed"
    assert _history(run, "seo") == ["pending", "active", "done"]
    seo_active = [e for e in run.events if isinstance(e, AiStepEvent) and e.state == "active"][-1]
    assert seo_active.detail == "Writing from the design and brief alone"
    assert MARKET_BEGIN not in provider.task("seo").prompt_text
    saved = market_snapshot.load(chain.workspace, LISTING)
    assert saved is not None
    assert saved.empty is True
    assert run.phase == "done"


def test_a_failed_etsy_search_fails_the_run_with_the_spec_message(chain: Chain) -> None:
    assert chain.market is not None
    chain.market.fail("search_active", server_error(503), times=12)

    run = chain.run(draft_brief=False)

    assert _history(run, "market") == ["pending", "active", "active", "failed"]
    message = _detail(run, "market")
    assert message is not None
    assert message.startswith("Etsy market search failed: ")
    assert _history(run, "seo") == ["pending", "pending"]
    assert _detail(run, "seo") == "Not started"
    assert run.phase == "failed"
    assert run.events[-1].model_dump()["message"] == message
    assert "seo" not in chain.provider.calls
    assert "market" not in _types(run)


def test_a_failed_search_keeps_the_previous_snapshot(chain: Chain) -> None:
    chain.run(draft_brief=False)
    before = market_snapshot.load(chain.workspace, LISTING)
    assert chain.market is not None
    chain.market.fail("search_active", server_error(503), times=12)
    shutil.rmtree(chain.workspace.market_search_cache_dir())

    run = chain.run(draft_brief=False)

    assert run.phase == "failed"
    assert market_snapshot.load(chain.workspace, LISTING) == before


def test_a_workspace_without_an_etsy_key_fails_at_market_search(
    workspace_root: Path, provider: ChainProvider
) -> None:
    seed_prompts(workspace_root)
    chain = Chain(workspace_root, provider, None)

    run = chain.run(draft_brief=False)

    assert _state(run) == {"brief": "skipped", "market": "failed", "seo": "pending"}
    detail = _detail(run, "market")
    assert detail is not None
    assert detail.startswith("Etsy market search failed: ")


def test_a_failed_extraction_fails_the_run_before_any_search(
    workspace_root: Path,
) -> None:
    seed_prompts(workspace_root)
    provider = ChainProvider(failures={"queries": SeoTryAgainError("codex: malformed queries")})
    chain = Chain(workspace_root, provider, seeded_market())

    run = chain.run(draft_brief=False)

    assert _state(run) == {"brief": "skipped", "market": "failed", "seo": "pending"}
    assert _detail(run, "market") == "codex: malformed queries"
    assert _detail(run, "seo") == "Not started"
    assert chain.market is not None
    assert chain.market.calls == []
    assert run.phase == "failed"


def test_a_failed_brief_fails_the_run_and_nothing_else_starts(workspace_root: Path) -> None:
    seed_prompts(workspace_root)
    edit_listing(workspace_root, brief="")
    provider = ChainProvider(failures={"brief": SeoTryAgainError("codex: no brief")})
    chain = Chain(workspace_root, provider, seeded_market())

    run = chain.run(draft_brief=True)

    assert _history(run, "brief") == ["pending", "active", "failed"]
    assert _detail(run, "brief") == "codex: no brief"
    assert _state(run) == {"brief": "failed", "market": "pending", "seo": "pending"}
    assert _detail(run, "market") == "Not started"
    assert run.phase == "failed"
    assert chain.saved_brief() == ""


def test_a_failed_proposal_fails_the_seo_node(workspace_root: Path) -> None:
    seed_prompts(workspace_root)
    provider = ChainProvider(failures={"seo": SeoTryAgainError("codex: still malformed")})
    chain = Chain(workspace_root, provider, seeded_market())

    run = chain.run(draft_brief=False)

    assert _state(run) == {"brief": "skipped", "market": "done", "seo": "failed"}
    assert run.events[-1].model_dump()["message"] == "codex: still malformed"
    assert "proposal" not in _types(run)


def test_a_defect_fails_the_run_with_the_generic_message(workspace_root: Path) -> None:
    seed_prompts(workspace_root)
    provider = ChainProvider(failures={"seo": KeyError("internal detail")})
    chain = Chain(workspace_root, provider, seeded_market())

    run = chain.run(draft_brief=False)

    assert run.phase == "failed"
    assert run.events[-1].model_dump()["message"] == INTERNAL_ERROR_MESSAGE
    assert _detail(run, "seo") == INTERNAL_ERROR_MESSAGE


# --------------------------------------------------------------- brief write


def test_a_brief_filled_in_mid_draft_is_kept_and_not_overwritten(chain: Chain) -> None:
    edit_listing(chain.workspace.root, brief="")
    chain.provider.during["brief"] = lambda: edit_listing(chain.workspace.root, brief=SELLER_BRIEF)

    run = chain.run(draft_brief=True)

    brief = next(e for e in run.events if e.type == "brief")
    assert brief.model_dump(include={"text", "written"}) == {
        "text": DRAFTED_BRIEF,
        "written": False,
    }
    assert chain.saved_brief() == SELLER_BRIEF
    assert _history(run, "brief") == ["pending", "active", "done"]
    assert SELLER_BRIEF in chain.provider.task("queries").prompt_text


def test_the_brief_write_waits_for_a_patch_holding_the_lock(chain: Chain) -> None:
    edit_listing(chain.workspace.root, brief="")
    lock = chain.locks.listing(LISTING)
    lock.__enter__()
    try:
        run = chain.start(draft_brief=True)
        wait_for(lambda: chain.provider.started["brief"].is_set())
        assert not _becomes(run, lambda: "brief" in _types(run), timeout=0.3)
        # The PATCH that held the lock writes the seller's brief.
        edit_listing(chain.workspace.root, brief=SELLER_BRIEF)
    finally:
        lock.__exit__(None, None, None)

    wait_until_finished(run)
    brief = next(e for e in run.events if e.type == "brief")
    assert brief.model_dump()["written"] is False
    assert chain.saved_brief() == SELLER_BRIEF


def _listings_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "listings").rglob("*"))
        if path.is_file()
    }


def test_the_brief_is_the_only_write_under_listings(chain: Chain) -> None:
    root = chain.workspace.root
    before_run = _listings_tree(root)

    chain.run(draft_brief=False)
    assert _listings_tree(root) == before_run

    edit_listing(root, brief="")
    listing_file = root / "listings" / LISTING / "listing.yaml"
    document_before = yaml.safe_load(listing_file.read_text(encoding="utf-8"))
    before_draft = _listings_tree(root)

    chain.run(draft_brief=True)

    after = _listings_tree(root)
    changed = {path for path in after if after[path] != before_draft.get(path)}
    assert changed == {f"listings/{LISTING}/listing.yaml"}
    document_after = yaml.safe_load(listing_file.read_text(encoding="utf-8"))
    assert document_after == {**document_before, "brief": DRAFTED_BRIEF}


# -------------------------------------------------------------- cancellation


class BlockingSearch(FakeEtsyMarketClient):
    """A market whose searches wait for the run's cancel event."""

    def __init__(self, cancel: threading.Event) -> None:
        super().__init__()
        self.cancel = cancel
        self.searching = threading.Event()

    def search_active(self, query: str, *, limit: int = 25):  # noqa: ANN201 - the fake's own
        self.searching.set()
        self.cancel.wait(10)
        return super().search_active(query, limit=limit)


@pytest.mark.parametrize("step", ["brief", "queries", "seo"])
def test_cancelling_during_a_provider_call_kills_it_and_emits_no_proposal(
    chain: Chain, step: str
) -> None:
    edit_listing(chain.workspace.root, brief="")
    chain.provider.gate(step)  # type: ignore[arg-type]
    run = chain.start(draft_brief=True)
    wait_for(lambda: chain.provider.started[step].is_set())  # type: ignore[index]

    assert run.request_stop("cancelled")
    wait_until_finished(run)

    assert chain.provider.cancelled == [step]
    assert run.phase == "cancelled"
    assert "proposal" not in _types(run)
    assert run.active_step is None
    written = chain.saved_brief()
    assert written == ("" if step == "brief" else DRAFTED_BRIEF)
    has_snapshot = market_snapshot.load(chain.workspace, LISTING) is not None
    assert has_snapshot is (step == "seo")


def test_cancelling_during_market_search_stops_research(
    workspace_root: Path, provider: ChainProvider
) -> None:
    seed_prompts(workspace_root)
    chain = Chain(workspace_root, provider, None)
    registry_run = chain.registry.create(LISTING, draft_brief=False)
    assert isinstance(registry_run, AiRun)
    market = BlockingSearch(registry_run.cancel_event)
    chain.runner.market_client = lambda _workspace: market
    chain.runner.start(registry_run)
    wait_for(market.searching.is_set)

    registry_run.request_stop("cancelled")
    run = wait_until_finished(registry_run)

    assert run.phase == "cancelled"
    assert _state(run) == {"brief": "skipped", "market": "pending", "seo": "pending"}
    assert _detail(run, "market") == "Cancelled"
    assert market_snapshot.load(chain.workspace, LISTING) is None
    assert "seo" not in provider.calls


# ------------------------------------------------------------------ watchdog


def test_the_watchdog_fails_a_run_that_outlives_three_minutes(chain: Chain) -> None:
    chain.provider.gate("seo")
    run = chain.start(draft_brief=False)
    wait_for(lambda: chain.provider.started["seo"].is_set())

    chain.clock.now = RUN_LIMIT_SECONDS - 1
    assert not _becomes(run, lambda: run.finished, timeout=0.1)
    chain.clock.now = RUN_LIMIT_SECONDS
    wait_until_finished(run)

    assert RUN_LIMIT_SECONDS == 180
    assert run.phase == "failed"
    assert run.events[-1].model_dump()["message"] == TIMEOUT_MESSAGE
    assert _state(run) == {"brief": "skipped", "market": "done", "seo": "failed"}
    assert _detail(run, "seo") == TIMEOUT_MESSAGE
    assert chain.provider.cancelled == ["seo"]


# ------------------------------------------------------------------ threads


def test_each_run_has_its_own_daemon_thread_and_shutdown_cancels_it(chain: Chain) -> None:
    chain.provider.gate("queries")
    run = chain.start(draft_brief=False)
    wait_for(lambda: chain.provider.started["queries"].is_set())
    threads = [t for t in threading.enumerate() if t.name.startswith("ai-run-")]
    assert threads
    assert all(thread.daemon for thread in threads)

    chain.runner.shutdown()

    assert run.phase == "cancelled"
    assert run.stop_reason == "shutdown"
    assert not any(t.is_alive() for t in threads)


# ------------------------------------------------------------ workspace facts


def test_listings_from_the_sellers_own_shop_are_marked(chain: Chain) -> None:
    set_etsy_shop_id(chain.workspace.root, 1002)
    chain.workspace = Workspace.discover(root_override=chain.workspace.root)
    chain.runner.workspace = chain.workspace

    chain.run(draft_brief=False)

    saved = market_snapshot.load(chain.workspace, LISTING)
    assert saved is not None
    assert {listing.listing_id for listing in saved.listings if listing.own_shop} == {2}


def test_each_run_reads_the_weights_from_settings_yaml(chain: Chain) -> None:
    settings = chain.workspace.settings_file()
    settings.write_text(
        "market_seo:\n  weights:\n"
        + "".join(
            f"    {metric}: 0\n"
            for metric in (
                "reviews",
                "favourites_per_day",
                "search_rank",
                "views_per_day",
                "shop_sales",
                "shop_rating",
            )
        ),
        encoding="utf-8",
    )

    run = chain.run(draft_brief=False)

    assert _state(run) == {"brief": "skipped", "market": "failed", "seo": "pending"}
    detail = _detail(run, "market")
    assert detail is not None
    assert "at least one market_seo weight must be above zero" in detail

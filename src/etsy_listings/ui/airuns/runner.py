"""The thread that runs one AI run's chain (market-seo.md, *The chain*,
*Failures* and *AI runs*).

1. **Brief**, only when the run asks for a draft and the saved brief is
   empty: draft it, then write it under the listing's write lock -- only if
   the brief is *still* empty when re-read there.
2. **Market**: extract three queries, research them through the 7-day
   cached client, save the snapshot. An empty result is a warning and the
   chain goes on; a failure fails the run.
3. **SEO**: the proposal, with the market block.

**A thread per run, never the plan/apply worker.** An AI run spends most of
its time waiting on a provider CLI or on Etsy, and a deploy must not queue
behind it (or it behind a deploy). The threads are daemons, and
:meth:`AiRunner.shutdown` cancels every active run, so neither a server
stopping nor a test suite ending waits on a provider.

**Stopping.** Each run has one cancel event. ``DELETE`` sets it, the
watchdog sets it after :data:`RUN_LIMIT_SECONDS`, and shutdown sets it. It
is handed to every provider call, which kills the subprocess tree, and to
``research``, which starts no new Etsy call; the chain also checks it
between steps. What was written before it was set -- a brief, a snapshot --
stays.

**Writes.** The guarded ``brief`` is the only workspace file this package
writes under ``listings/``. The snapshot lives in ``.cache/market/``, and is
saved under the same lock so a rename cannot move the listing between the
check and the write.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from etsy_listings.ai.brief import BriefRequest
from etsy_listings.ai.errors import ProviderCancelledError, SeoGenerationError
from etsy_listings.ai.market_queries import MarketQueriesRequest
from etsy_listings.ai.orchestrator import generate_brief, generate_market_queries, generate_proposal
from etsy_listings.ai.providers import AiProvider
from etsy_listings.clients.etsy.market import EtsyMarketClient
from etsy_listings.config.garment_profile import GarmentProfile
from etsy_listings.config.listing import Listing
from etsy_listings.errors import INTERNAL_ERROR_MESSAGE, UserFacingError
from etsy_listings.market import MarketResearchError, ResearchCancelled, research
from etsy_listings.market import snapshot as market_snapshot
from etsy_listings.market.cache import CachedEtsyMarketClient
from etsy_listings.ui.airuns.events import (
    STEP_IDS,
    AiBriefEvent,
    AiMarketEvent,
    AiProposalEvent,
    AiQueriesEvent,
)
from etsy_listings.ui.airuns.registry import AiRun, AiRunRegistry
from etsy_listings.ui.api.listings import replace_listing_yaml
from etsy_listings.ui.api.seo import (
    build_seo_request,
    primary_design_image,
    proposal_response,
    proposal_snapshot,
)
from etsy_listings.ui.workspace_locks import WorkspaceLocks
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

RUN_LIMIT_SECONDS = 180.0
"""The whole run's cap (market-seo.md, *Failures*). Each provider call keeps
its own 60 seconds; market search has no limit of its own."""

TIMEOUT_MESSAGE = "The AI run took longer than 3 minutes, so it was stopped. Try again."
KEPT_BRIEF = "You wrote the brief, so it was kept"
KEPT_OWN_BRIEF = "You wrote the brief meanwhile, so yours was kept"
NO_COMPARABLES = "No comparable listings found, even with filters relaxed"
NOT_STARTED = "Not started"
CANCELLED = "Cancelled"
NO_ETSY_KEY = "no Etsy API key is configured; run `etsy-listings setup`"

ProviderFactory = Callable[[Workspace], Sequence[AiProvider]]
MarketClientFactory = Callable[[Workspace], EtsyMarketClient | None]
"""The uncached market client, or ``None`` when the workspace has no Etsy
key. The runner wraps it in the workspace's caches itself."""


class _Stopped(Exception):
    """The run's cancel event was seen between steps."""


def _read_prompt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserFacingError(
            f"{path} could not be read; run `etsy-listings setup` to seed it ({exc})"
        ) from exc


@dataclass
class AiRunner:
    workspace: Workspace
    registry: AiRunRegistry
    locks: WorkspaceLocks
    providers: ProviderFactory
    market_client: MarketClientFactory
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic: Callable[[], float] = time.monotonic
    limit_seconds: float = RUN_LIMIT_SECONDS
    watch_interval: float = 0.5
    _threads: list[threading.Thread] = field(default_factory=list, init=False, repr=False)
    _threads_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def start(self, run: AiRun) -> None:
        """Run the chain on a new daemon thread, with its watchdog."""
        started = self.monotonic()
        threads = [
            threading.Thread(target=self._execute, args=(run,), name=f"ai-run-{run.id}"),
            threading.Thread(
                target=self._watch, args=(run, started), name=f"ai-run-watchdog-{run.id}"
            ),
        ]
        with self._threads_lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            for thread in threads:
                thread.daemon = True
                thread.start()
                self._threads.append(thread)

    def shutdown(self, *, timeout: float = 10.0) -> None:
        """Cancel every active run and wait (bounded) for its thread."""
        for run in self.registry.active():
            run.request_stop("shutdown")
        with self._threads_lock:
            threads = list(self._threads)
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    # ------------------------------------------------------------ the thread

    def _watch(self, run: AiRun, started: float) -> None:
        while not run.cancel_event.wait(self.watch_interval):
            if run.finished:
                return
            if self.monotonic() - started >= self.limit_seconds:
                run.request_stop("timeout")
                return

    def _execute(self, run: AiRun) -> None:
        try:
            self._chain(run)
        except (_Stopped, ProviderCancelledError, ResearchCancelled):
            self._end_stopped(run)
        except Exception as exc:
            if run.cancel_event.is_set():
                self._end_stopped(run)
            elif isinstance(exc, SeoGenerationError | UserFacingError):
                self._end_failed(run, str(exc))
            else:
                logger.exception(
                    "AI run %s for %s ended with an unhandled error", run.id, run.listing
                )
                self._end_failed(run, INTERNAL_ERROR_MESSAGE)
        finally:
            # A defect in the ending itself must still end the run.
            run.finish("failed", INTERNAL_ERROR_MESSAGE)

    def _end_failed(self, run: AiRun, message: str) -> None:
        active = run.active_step
        for step in STEP_IDS:
            if step == active:
                run.step(step, "failed", message)
            elif _is_pending(run, step):
                run.step(step, "pending", NOT_STARTED)
        run.finish("failed", message)

    def _end_stopped(self, run: AiRun) -> None:
        if run.stop_reason == "timeout":
            self._end_failed(run, TIMEOUT_MESSAGE)
            return
        active = run.active_step
        for step in STEP_IDS:
            if step == active:
                run.step(step, "pending", CANCELLED)
            elif _is_pending(run, step):
                run.step(step, "pending", NOT_STARTED)
        run.finish("cancelled")

    # ------------------------------------------------------------- the chain

    def _check(self, run: AiRun) -> None:
        if run.cancel_event.is_set():
            raise _Stopped

    def _load(self, run: AiRun) -> tuple[Listing, GarmentProfile]:
        """The listing as saved now, and its garment profile."""
        if not self.workspace.listing_file(run.listing).is_file():
            raise UserFacingError(f"the listing {run.listing!r} no longer exists")
        listing = self.workspace.load_listing(run.listing)
        profile = WorkspaceFacts.gather(self.workspace).garment_profile(listing.garment_profile)
        if profile is None:
            raise UserFacingError("the listing has no usable garment profile")
        return listing, profile

    def _chain(self, run: AiRun) -> None:
        workspace = self.workspace
        listing, profile = self._load(run)
        providers = self.providers(workspace)
        design = primary_design_image(workspace, run.listing, listing)
        drafting = run.draft_brief and not listing.brief.strip()

        run.step("brief", "pending" if drafting else "skipped", None if drafting else KEPT_BRIEF)
        run.step("market", "pending")
        run.step("seo", "pending")

        if drafting:
            run.step("brief", "active", f"Reading {design.name}")
            drafted = generate_brief(
                BriefRequest(design_image=design),
                _read_prompt(workspace.brief_prompt_file()),
                providers,
                cancel_event=run.cancel_event,
            )
            self._check(run)
            written = self._write_brief(run.listing, drafted.brief)
            run.emit(lambda seq: AiBriefEvent(seq=seq, text=drafted.brief, written=written))
            run.step(
                "brief",
                "done",
                f"Drafted from {design.name}"
                if written
                else "You wrote the brief, so yours was kept",
            )
            listing, profile = self._load(run)

        run.step("market", "active", "Choosing Etsy searches from the brief")
        if not listing.brief.strip():
            raise UserFacingError("the listing brief is empty")
        queries = generate_market_queries(
            MarketQueriesRequest(
                brief=listing.brief,
                garment_title=profile.blueprint.display_title,
                design_image=design,
            ),
            _read_prompt(workspace.market_queries_prompt_file()),
            providers,
            cancel_event=run.cancel_event,
        ).queries
        self._check(run)
        run.emit(lambda seq: AiQueriesEvent(seq=seq, queries=list(queries)))
        run.step("market", "active", f"Searching Etsy for {len(queries)} phrases…")

        inner = self.market_client(workspace)
        if inner is None:
            raise MarketResearchError(NO_ETSY_KEY)
        result = research(
            queries,
            CachedEtsyMarketClient.in_workspace(inner, workspace),
            today=self.now(),
            weights=workspace.load_settings().market_seo.weights,
            own_shop_id=workspace.defaults.etsy.shop_id,
            cancel_event=run.cancel_event,
        )
        self._check(run)
        snapshot = market_snapshot.MarketSnapshot.of(result, searched_at=self.now())
        with self.locks.listing(run.listing):
            if workspace.listing_file(run.listing).is_file():
                market_snapshot.save(workspace, run.listing, snapshot)
        run.emit(lambda seq: AiMarketEvent(seq=seq, snapshot=snapshot))
        if result.empty:
            run.step("market", "warning", NO_COMPARABLES)
        else:
            run.step(
                "market", "done", f"{result.scored} listings scored, from {result.found} found"
            )

        run.step(
            "seo",
            "active",
            "Writing from the design and brief alone"
            if result.empty
            else "Writing from the market data",
        )
        listing, profile = self._load(run)
        request = build_seo_request(
            workspace, run.listing, listing, profile, market_block=snapshot.block
        )
        frozen = proposal_snapshot(workspace, run.listing, listing, request)
        proposal = generate_proposal(
            request,
            _read_prompt(workspace.seo_prompt_file()),
            providers,
            cancel_event=run.cancel_event,
        )
        self._check(run)
        response = proposal_response(proposal, frozen)
        run.emit(lambda seq: AiProposalEvent(seq=seq, **response.model_dump()))
        run.step(
            "seo",
            "done",
            f"{len(proposal.titles)} titles, {len(proposal.tags)} tags, "
            f"{len(proposal.description_leads)} leads to review",
        )
        run.finish("done")

    def _write_brief(self, name: str, text: str) -> bool:
        """Write ``text`` as the listing's brief if the saved one is still
        empty, under the lock PATCH autosave and rename take."""
        with self.locks.listing(name):
            path = self.workspace.listing_file(name)
            if not path.is_file():
                return False
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if str(document.get("brief") or "").strip():
                return False
            document["brief"] = text
            replace_listing_yaml(path, document)
            return True


def _is_pending(run: AiRun, step: str) -> bool:
    return next(s.state for s in run.steps if s.id == step) == "pending"

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from etsy_listings.core.ai.brief import BriefRequest
from etsy_listings.core.ai.errors import ProviderCancelledError, SeoGenerationError
from etsy_listings.core.ai.listing_inputs import ListingAiInputs, PreparedSeo
from etsy_listings.core.ai.market_queries import MarketQueriesRequest
from etsy_listings.core.ai.models import AiLimits, Deadline, RunBudget
from etsy_listings.core.ai.orchestrator import (
    generate_brief,
    generate_market_queries,
    generate_proposal,
)
from etsy_listings.core.ai.proposals import ProposalChoices, ProposalStore
from etsy_listings.core.ai.providers import AiProvider
from etsy_listings.core.application.ai.events import (
    STEP_IDS,
    AiBriefEvent,
    AiMarketEvent,
    AiProposalEvent,
    AiQueriesEvent,
)
from etsy_listings.core.application.ai.readiness import ProviderFactory
from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry
from etsy_listings.core.application.dependencies import MarketClientFactory
from etsy_listings.core.config.market_weights import MarketWeights
from etsy_listings.core.errors import INTERNAL_ERROR_MESSAGE, UserFacingError
from etsy_listings.core.market import (
    MarketResearchError,
    MarketResult,
    ResearchCancelledError,
    ResearchSettings,
    research,
)
from etsy_listings.core.market import snapshot as market_snapshot
from etsy_listings.core.market.cache import CachedEtsyMarketClient
from etsy_listings.core.workspace.listing_documents import (
    Document,
    ListingDocuments,
    ListingMissingError,
)
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

KEPT_BRIEF = "You wrote the brief, so it was kept"
KEPT_OWN_BRIEF = "You wrote the brief meanwhile, so yours was kept"
NO_COMPARABLES = "No comparable listings found, even with filters relaxed"
NOT_STARTED = "Not started"
CANCELLED = "Cancelled"
NO_ETSY_KEY = "no Etsy API key is configured; run `etsy-listings setup`"


def timeout_message(run_minutes: int) -> str:
    return f"The AI run took longer than {run_minutes} minutes, so it was stopped. Try again."


@dataclass(frozen=True)
class _Captured:
    providers: Sequence[AiProvider]
    budget: RunBudget
    weights: MarketWeights


class _CancelledBetweenStepsError(Exception): ...


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
    providers: ProviderFactory
    market_client: MarketClientFactory
    proposals: ProposalStore
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic: Callable[[], float] = time.monotonic
    watch_interval: float = 0.5
    _threads: list[threading.Thread] = field(default_factory=list, init=False, repr=False)
    _threads_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def start(self, run: AiRun) -> None:
        started = self.monotonic()
        try:
            settings = self.workspace.capture_settings()
            limits = AiLimits.of(settings.ai)
            providers = tuple(self.providers(self.workspace, settings.ai))
        except UserFacingError as exc:
            self._end_failed(run, str(exc))
            return
        except Exception:
            logger.exception("AI run %s could not capture its providers", run.id)
            self._end_failed(run, INTERNAL_ERROR_MESSAGE)
            return
        budget = RunBudget(
            limits, Deadline(deadline_at=started + limits.run_seconds, clock=self.monotonic)
        )
        captured = _Captured(providers, budget, settings.market_seo.weights)
        threads = [
            threading.Thread(target=self._execute, args=(run, captured), name=f"ai-run-{run.id}"),
            threading.Thread(
                target=self._watch, args=(run, budget), name=f"ai-run-watchdog-{run.id}"
            ),
        ]
        with self._threads_lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            for thread in threads:
                thread.daemon = True
                thread.start()
                self._threads.append(thread)

    def shutdown(self, *, timeout: float = 10.0) -> None:
        for run in self.registry.active():
            run.request_stop("shutdown")
        with self._threads_lock:
            threads = list(self._threads)
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _watch(self, run: AiRun, budget: RunBudget) -> None:
        while not run.cancel_event.wait(self.watch_interval):
            if run.finished:
                return
            if budget.deadline.expired:
                run.request_stop("timeout")
                return

    def _execute(self, run: AiRun, captured: _Captured) -> None:
        budget = captured.budget
        try:
            self._chain(run, captured)
        except (_CancelledBetweenStepsError, ProviderCancelledError, ResearchCancelledError):
            self._end_stopped(run, budget)
        except Exception as exc:
            if run.cancel_event.is_set():
                self._end_stopped(run, budget)
            elif isinstance(exc, SeoGenerationError | UserFacingError):
                self._end_failed(run, str(exc))
            else:
                logger.exception(
                    "AI run %s for %s ended with an unhandled error", run.id, run.listing
                )
                self._end_failed(run, INTERNAL_ERROR_MESSAGE)
        finally:
            run.fail_unless_finished(INTERNAL_ERROR_MESSAGE)

    def _end_failed(self, run: AiRun, message: str) -> None:
        active = run.active_step
        for step in STEP_IDS:
            if step == active:
                run.step(step, "failed", message)
            elif _is_pending(run, step):
                run.step(step, "pending", NOT_STARTED)
        run.finish("failed", message)

    def _end_stopped(self, run: AiRun, budget: RunBudget) -> None:
        if run.stop_reason == "timeout":
            self._end_failed(run, timeout_message(budget.limits.run_minutes))
            return
        active = run.active_step
        for step in STEP_IDS:
            if step == active:
                run.step(step, "pending", CANCELLED)
            elif _is_pending(run, step):
                run.step(step, "pending", NOT_STARTED)
        run.finish("cancelled")

    def _check(self, run: AiRun) -> None:
        if run.cancel_event.is_set():
            raise _CancelledBetweenStepsError

    def _load(self, run: AiRun, *, market_block: str = "") -> PreparedSeo:
        return ListingAiInputs.read(self.workspace, run.listing).prepare(market_block=market_block)

    def _chain(self, run: AiRun, captured: _Captured) -> None:
        # Cancel batch can land after the queue claimed the row, before this ran.
        self._check(run)
        inputs = self._load(run)
        drafting = run.draft_brief and not inputs.request.brief.strip()

        brief_only = run.origin == "batch"
        _plan_steps(run, drafting=drafting, brief_only=brief_only)

        if drafting:
            self._draft_brief(run, inputs.request.design_image, captured)

        if brief_only:
            self._check(run)
            run.finish("done")
            return

        if drafting:
            inputs = self._load(run)
        result, snapshot = self._research_market(run, inputs, captured)
        self._propose(run, result, snapshot, captured)
        run.finish("done")

    def _draft_brief(self, run: AiRun, design: Path, captured: _Captured) -> None:
        run.step("brief", "active", f"Reading {design.name}")
        drafted = generate_brief(
            BriefRequest(design_image=design),
            _read_prompt(self.workspace.brief_prompt_file()),
            captured.providers,
            budget=captured.budget,
            cancel_event=run.cancel_event,
        )
        self._check(run)
        written = self._write_brief(run.listing, drafted.brief)
        run.emit(lambda seq: AiBriefEvent(seq=seq, text=drafted.brief, written=written))
        run.step(
            "brief",
            "done",
            f"Drafted from {design.name}" if written else "You wrote the brief, so yours was kept",
        )

    def _research_market(
        self, run: AiRun, inputs: PreparedSeo, captured: _Captured
    ) -> tuple[MarketResult, market_snapshot.MarketSnapshot]:
        workspace = self.workspace
        run.step("market", "active", "Choosing Etsy searches from the brief")
        if not inputs.request.brief.strip():
            raise UserFacingError("the listing brief is empty")
        queries = generate_market_queries(
            MarketQueriesRequest(
                brief=inputs.request.brief,
                garment_title=inputs.request.product_type,
                design_image=inputs.request.design_image,
            ),
            _read_prompt(workspace.market_queries_prompt_file()),
            captured.providers,
            budget=captured.budget,
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
            settings=ResearchSettings(
                weights=captured.weights,
                own_shop_id=workspace.defaults.etsy.shop_id,
            ),
            cancel_event=run.cancel_event,
        )
        self._check(run)
        snapshot = market_snapshot.MarketSnapshot.of(result, searched_at=self.now())
        documents = ListingDocuments(workspace)
        with documents.lock(run.listing):
            if documents.exists(run.listing):
                market_snapshot.save(workspace, run.listing, snapshot)
        run.emit(lambda seq: AiMarketEvent(seq=seq, snapshot=snapshot))
        if result.empty:
            run.step("market", "warning", NO_COMPARABLES)
        else:
            run.step(
                "market", "done", f"{result.scored} listings scored, from {result.found} found"
            )
        return result, snapshot

    def _propose(
        self,
        run: AiRun,
        result: MarketResult,
        snapshot: market_snapshot.MarketSnapshot,
        captured: _Captured,
    ) -> None:
        workspace = self.workspace
        run.step(
            "seo",
            "active",
            "Writing from the design and brief alone"
            if result.empty
            else "Writing from the market data",
        )
        inputs = self._load(run, market_block=snapshot.block)
        proposal = generate_proposal(
            inputs.request,
            _read_prompt(workspace.seo_prompt_file()),
            captured.providers,
            budget=captured.budget,
            cancel_event=run.cancel_event,
        )
        self._check(run)
        # A delete stops the run before taking the lock; its cleanup will not
        # come back for a stop seen here.
        documents = ListingDocuments(workspace)
        with documents.lock(run.listing):
            self._check(run)
            if not documents.exists(run.listing):
                raise UserFacingError(f"the listing {run.listing!r} no longer exists")
            record = self.proposals.put(
                run.listing,
                ProposalChoices.of(proposal),
                inputs.snapshot,
                generated_at=datetime.now(UTC),
                origin=run.origin,
            )
            announced = ListingAiInputs.read(workspace, run.listing).judge(record)
        run.emit(lambda seq: AiProposalEvent(seq=seq, **announced.model_dump()))
        run.step(
            "seo",
            "done",
            f"{len(proposal.titles)} titles, {len(proposal.tags)} tags, "
            f"{len(proposal.description_leads)} leads to review",
        )

    def _write_brief(self, name: str, text: str) -> bool:
        def fill(document: Document) -> Document | None:
            if str(document.get("brief") or "").strip():
                return None
            return {**document, "brief": text}

        try:
            return ListingDocuments(self.workspace).edit(name, fill) is not None
        except ListingMissingError:
            return False


def _plan_steps(run: AiRun, *, drafting: bool, brief_only: bool) -> None:
    run.step("brief", "pending" if drafting else "skipped", None if drafting else KEPT_BRIEF)
    for step in ("market", "seo"):
        run.step(
            step,
            "skipped" if brief_only else "pending",
            "Start AI Mode after reviewing the brief" if brief_only else None,
        )


def _is_pending(run: AiRun, step: str) -> bool:
    return next(s.state for s in run.steps if s.id == step) == "pending"

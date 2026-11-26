from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.ai.readiness import (
    ProviderFactory,
    current_providers,
    default_ai_providers,
    unready_reason,
)
from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry, Conflict, Deploying
from etsy_listings.core.application.ai.runner import AiRunner
from etsy_listings.core.application.dependencies import (
    MarketClientFactory,
    default_market_client,
)
from etsy_listings.core.application.job_gate import JobGate, Ticket
from etsy_listings.core.application.refusals import (
    AiNotReadyError,
    AiRunRefusedError,
    ListingDeployingError,
    ListingDraftingInBatchError,
    ListingMissingError,
)
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.config.settings import SettingsProblem
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


class AiCoordinator:
    def __init__(  # noqa: PLR0913 -- the gate joins the host seams; each has a default but the stores
        self,
        workspace: Workspace,
        *,
        proposals: ProposalStore,
        batches: BatchStore,
        providers: ProviderFactory = default_ai_providers,
        market_client: MarketClientFactory = default_market_client,
        gate: JobGate | None = None,
    ) -> None:
        self._workspace = workspace
        self._gate = gate if gate is not None else JobGate()
        self._registry = AiRunRegistry()
        self._runner = AiRunner(
            workspace=workspace,
            registry=self._registry,
            providers=providers,
            market_client=market_client,
            proposals=proposals,
        )
        self._queue = BatchQueue(
            workspace=workspace,
            batches=batches,
            registry=self._registry,
            runner=self._runner,
            gate=self._gate,
        )

    @property
    def registry(self) -> AiRunRegistry:
        return self._registry

    @property
    def queue(self) -> BatchQueue:
        return self._queue

    def start(self) -> None:
        self._queue.start()

    def stop(self) -> None:
        self._queue.stop()
        self._runner.shutdown()

    def start_run(self, listing: str, *, draft_brief: bool) -> AiRun | Conflict:
        """Start a manual run for saved ``listing`` on its own thread, or
        answer the active run already holding it, to reattach to.

        Refusals, with nothing started: :class:`ListingMissingError`, then
        :class:`ListingDeployingError` (ADR-0050 wins over everything below),
        :class:`ListingDraftingInBatchError`, and -- after the active-run check --
        :class:`AiNotReadyError` with the readiness rule that failed.

        While a backup's pause is on, the run is answered ``queued`` and
        starts when the pause ends.
        """
        if not ListingDocuments(self._workspace).exists(listing):
            raise ListingMissingError(listing)
        refused = self._claimed(listing)
        if refused is not None:
            raise refused
        active = self._registry.latest(listing)
        if active is not None and not active.finished:
            return Conflict(active_run=active.id)
        reason = self._unready(listing, draft_brief=draft_brief)
        if reason is not None:
            raise AiNotReadyError(listing, reason)
        return self._create(listing, draft_brief=draft_brief)

    def _create(self, listing: str, *, draft_brief: bool) -> AiRun | Conflict:
        """Create the run and start it, or hold it while a backup's pause is
        on. Admitted before the run exists, so a backup waiting for quiet
        counts it from the moment anyone can see it; the run owns the
        ticket from then on."""
        ticket = self._gate.admit(_job(listing))
        # The registry refuses a held listing again here, which is what
        # closes the race with a deploy taking it since the check above.
        run = self._registry.create(
            listing, draft_brief=draft_brief, queued=ticket is None, ticket=ticket
        )
        if isinstance(run, Deploying):
            raise ListingDeployingError(listing)
        if isinstance(run, Conflict):
            return run
        if ticket is None:
            self._gate.hold(_job(listing), lambda admitted: self._begin(run, admitted))
        else:
            self._runner.start(run)
        return run

    def _begin(self, run: AiRun, ticket: Ticket) -> None:
        if run.begin(ticket):
            self._runner.start(run)

    def blocked(self, listing: str) -> AiRunRefusedError | None:
        """What :meth:`start_run` would refuse saved ``listing`` with for
        the **AI Mode** button's run -- one that drafts an empty brief -- or
        ``None`` when it would start. An active run is not a refusal: the
        button reattaches to it."""
        refused = self._claimed(listing)
        if refused is not None:
            return refused
        reason = self._unready(listing, draft_brief=True)
        return AiNotReadyError(listing, reason) if reason is not None else None

    def _claimed(self, listing: str) -> AiRunRefusedError | None:
        if self._registry.deploying(listing):
            return ListingDeployingError(listing)
        if self._queue.pending(listing):
            return ListingDraftingInBatchError(listing)
        return None

    def _unready(self, listing: str, *, draft_brief: bool) -> str | None:
        saved = self._workspace.load_listing(listing)
        providers = current_providers(self._runner.providers, self._workspace)
        if isinstance(providers, SettingsProblem):
            return providers.message
        return unready_reason(
            self._workspace,
            saved,
            providers,
            draft_brief=draft_brief,
        )

    def waiting_for_backup(self, run: AiRun) -> bool:
        return self._gate.holds(queued=run.phase == "queued")

    @contextmanager
    def yield_to_deploy(self, listings: Sequence[str]) -> Iterator[None]:
        with self._queue.yield_to_deploy(listings):
            yield


def _job(listing: str) -> str:
    """What a backup waiting for this run names."""
    return f"AI run for {listing}"

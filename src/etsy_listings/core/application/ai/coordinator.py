"""The AI coordinator: one per application runtime (ADR-0048, ADR-0050).

What a host needs to run AI work -- start a manual run, say whether one may
start, hand listings to a deploy -- behind one object whose lifetime the host
controls, as ``deploy/deployments.py`` is for deployment runs. Constructing it
starts nothing: :meth:`AiCoordinator.start` starts the batch dispatcher after
returning interrupted rows to the queue, and :meth:`AiCoordinator.stop` stops
the dispatcher *before* cancelling the active runs, so a run ending on the
way out frees no slot for the next row. The UI server's lifespan makes both
calls, around the deployment coordinator's; a test makes them directly.

Its parts stay in their modules and two are shared beyond it: the
``registry`` -- who holds a listing, which renaming and deleting a listing
consult -- and the batch ``queue``, which the seller's batch controls steer.
Each run gets its own thread (``runner``), never the deployment worker; the
queue is process-local and guards no second server on the workspace.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.ai.readiness import (
    ProviderFactory,
    default_ai_providers,
    unready_reason,
)
from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry, Conflict, Deploying
from etsy_listings.core.application.ai.runner import AiRunner
from etsy_listings.core.application.dependencies import (
    MarketClientFactory,
    default_market_client,
)
from etsy_listings.core.application.refusals import (
    AiNotReady,
    AiRunRefused,
    ListingDeploying,
    ListingDraftingInBatch,
    ListingMissing,
)
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


class AiCoordinator:
    """Manual and batch AI runs for one workspace."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        proposals: ProposalStore,
        batches: BatchStore,
        providers: ProviderFactory = default_ai_providers,
        market_client: MarketClientFactory = default_market_client,
    ) -> None:
        self._workspace = workspace
        self._registry = AiRunRegistry()
        self._runner = AiRunner(
            workspace=workspace,
            registry=self._registry,
            providers=providers,
            market_client=market_client,
            proposals=proposals,
        )
        self._queue = BatchQueue(
            workspace=workspace, batches=batches, registry=self._registry, runner=self._runner
        )

    @property
    def registry(self) -> AiRunRegistry:
        """Every run, by id and by listing: what a reader reattaches to, and
        what renaming or deleting a listing stops and forgets."""
        return self._registry

    @property
    def queue(self) -> BatchQueue:
        """The batch AI queue, as the batch controls steer and read it."""
        return self._queue

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Return rows a previous process left ``running`` to the queue, then
        start dispatching (ADR-0048)."""
        self._queue.start()

    def stop(self) -> None:
        """Start nothing more, then cancel every active run -- which kills
        its provider's process tree -- and wait (bounded) for its thread. A
        batch run stopped this way leaves its row ``running``, for the next
        :meth:`start` to rerun. Safe to call more than once."""
        self._queue.stop()
        self._runner.shutdown()

    # ---------------------------------------------------------- manual runs

    def start_run(self, listing: str, *, draft_brief: bool) -> AiRun | Conflict:
        """Start a manual run for saved ``listing`` on its own thread, or
        answer the active run already holding it, to reattach to.

        Refusals, with nothing started: :class:`ListingMissing`, then
        :class:`ListingDeploying` (ADR-0050 wins over everything below),
        :class:`ListingDraftingInBatch`, and -- after the active-run check --
        :class:`AiNotReady` with the readiness rule that failed.
        """
        if not ListingDocuments(self._workspace).exists(listing):
            raise ListingMissing(listing)
        refused = self._claimed(listing)
        if refused is not None:
            raise refused
        active = self._registry.latest(listing)
        if active is not None and not active.finished:
            return Conflict(active_run=active.id)
        reason = self._unready(listing, draft_brief=draft_brief)
        if reason is not None:
            raise AiNotReady(listing, reason)
        # The registry refuses a held listing again here, which is what
        # closes the race with a deploy taking it since the check above.
        run = self._registry.create(listing, draft_brief=draft_brief)
        if isinstance(run, Deploying):
            raise ListingDeploying(listing)
        if isinstance(run, Conflict):
            return run
        self._runner.start(run)
        return run

    def blocked(self, listing: str) -> AiRunRefused | None:
        """What :meth:`start_run` would refuse saved ``listing`` with for
        the **AI Mode** button's run -- one that drafts an empty brief -- or
        ``None`` when it would start. An active run is not a refusal: the
        button reattaches to it."""
        refused = self._claimed(listing)
        if refused is not None:
            return refused
        reason = self._unready(listing, draft_brief=True)
        return AiNotReady(listing, reason) if reason is not None else None

    def _claimed(self, listing: str) -> AiRunRefused | None:
        if self._registry.deploying(listing):
            return ListingDeploying(listing)
        if self._queue.pending(listing):
            return ListingDraftingInBatch(listing)
        return None

    def _unready(self, listing: str, *, draft_brief: bool) -> str | None:
        return unready_reason(
            self._workspace,
            self._workspace.load_listing(listing),
            self._runner.providers(self._workspace),
            draft_brief=draft_brief,
        )

    # -------------------------------------------------------------- deploys

    @contextmanager
    def yield_to_deploy(self, listings: Sequence[str]) -> Iterator[None]:
        """ADR-0050: take ``listings`` from AI work for as long as the
        ``with`` lasts. Their queued rows become ``cancelled_by_deploy``,
        every run on them is stopped and awaited, and no new run may start;
        on exit they are free again and the queue looks again."""
        with self._queue.yield_to_deploy(listings):
            yield

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

**A backup's pause** (workspace-backup spec, *Pausing jobs*) is the one time
a manual run waits: while the shared :class:`JobGate` is paused a new run is
accepted ``queued`` and held here, and resume starts the held runs in the
order they were asked for (plan decision P4). Each run that starts holds a
gate ticket until it finishes, which is what a backup's wait for quiet
counts.
"""

from __future__ import annotations

import threading
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
    """Manual and batch AI runs for one workspace."""

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
        self._lock = threading.Lock()
        self._held: list[AiRun] = []
        """Manual runs a backup's pause holds, in the order asked for."""
        self._tickets: dict[str, Ticket] = {}
        """The gate ticket of each manual run started, until it finishes."""
        self._registry.subscribe(self._release_ticket)
        self._gate.on_resume(self._release_held)

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
        :meth:`start` to rerun. Manual runs a backup's pause holds end
        ``cancelled`` without starting. Safe to call more than once."""
        self._queue.stop()
        with self._lock:
            held, self._held = self._held, []
        for run in held:
            run.request_stop("shutdown")
        self._runner.shutdown()

    # ---------------------------------------------------------- manual runs

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
        counts it from the moment anyone can see it."""
        ticket = self._gate.admit(_job(listing))
        # The registry refuses a held listing again here, which is what
        # closes the race with a deploy taking it since the check above.
        run = self._registry.create(listing, draft_brief=draft_brief, queued=ticket is None)
        if not isinstance(run, AiRun):
            if ticket is not None:
                ticket.release()
            if isinstance(run, Deploying):
                raise ListingDeployingError(listing)
            return run
        if ticket is None:
            with self._lock:
                self._held.append(run)
            # A resume can run its listener before this request queues the run.
            if not self._gate.paused:
                self._release_held()
        else:
            self._launch(run, ticket)
        return run

    def _launch(self, run: AiRun, ticket: Ticket) -> None:
        # Kept before the thread starts: a run that fails to capture its
        # providers finishes inside `start`, and its ticket must go with it.
        with self._lock:
            self._tickets[run.id] = ticket
        self._runner.start(run)

    def _release_ticket(self, run: AiRun) -> None:
        with self._lock:
            ticket = self._tickets.pop(run.id, None)
        if ticket is not None:
            ticket.release()

    def _release_held(self) -> None:
        """Resume: start the held runs in the order asked for. One stopped
        while held is skipped; a pause landing part way holds the rest."""
        for run, ticket in self._admit_held():
            if run.begin():
                self._launch(run, ticket)
            else:
                ticket.release()

    def _admit_held(self) -> list[tuple[AiRun, Ticket]]:
        admitted: list[tuple[AiRun, Ticket]] = []
        with self._lock:
            for run in self._held:
                ticket = self._gate.admit(_job(run.listing))
                if ticket is None:
                    break
                admitted.append((run, ticket))
            del self._held[: len(admitted)]
        return admitted

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

    # -------------------------------------------------------------- deploys

    @contextmanager
    def yield_to_deploy(self, listings: Sequence[str]) -> Iterator[None]:
        """ADR-0050: take ``listings`` from AI work for as long as the
        ``with`` lasts. Their queued rows become ``cancelled_by_deploy``,
        every run on them is stopped and awaited, and no new run may start;
        on exit they are free again and the queue looks again."""
        with self._queue.yield_to_deploy(listings):
            yield


def _job(listing: str) -> str:
    """What a backup waiting for this run names."""
    return f"AI run for {listing}"

"""The batch AI queue (spec, *Batch AI queue*; ADR-0048): every created batch row
drafts its brief, researches the market and gets a proposal, through the
same :class:`~etsy_listings.ui.airuns.runner.AiRunner` a manual run uses.

**One dispatcher thread**, woken by a condition whenever a row, a batch or a
run changes. Each wake reads ``batch_ai.concurrency`` afresh, counts the
batch runs still going, and starts queued rows until the limit is reached.
A row is started as an ordinary run with origin ``batch``; if a manual run
holds the listing, ``create`` answers a conflict and the row stays queued,
skipped until the next wake. Manual runs never count against the limit.

**Round-robin across batches**, oldest batch first (spec, *Scheduling*):
after serving one batch the next row comes from the batch after it, so a
25-row batch cannot hold back a 2-row one confirmed a minute later.

**The rows are the record.** Row states live in the batch record under
``.cache/batches/``, so the summary reads them after a restart, and
:meth:`BatchQueue.start` returns every ``running`` row to ``queued`` -- a
run does not survive its server, and its listing already exists, so the
rerun creates nothing twice. A run stopped by the server shutting down is
left ``running`` for that reason.

Only inside the ``ui`` server: there is no guard against two servers on one
workspace, and the in-process locks are enough (batch plan, *Where the queue
runs*).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from etsy_listings.batches import AiState, AiStep, Batch, BatchRow, BatchStore
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.ui.airuns.events import AiPhaseEvent
from etsy_listings.ui.airuns.registry import AiRun, AiRunRegistry
from etsy_listings.ui.airuns.runner import AiRunner
from etsy_listings.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

PENDING: frozenset[AiState] = frozenset({"queued", "running"})
"""A row in either state owns its listing's AI: the manual control is
refused while one exists (spec, *Scheduling*)."""

RESUMABLE: frozenset[AiState] = frozenset({"stopped", "cancelled"})
"""Not ``cancelled_by_deploy``: work a deploy cancelled must not resume onto
the deployed listing (ADR-0050; spec, *Deployment interaction*)."""
RETRYABLE: frozenset[AiState] = frozenset({"failed", "stopped", "cancelled", "cancelled_by_deploy"})

_ENDED: dict[str, AiState] = {"done": "done", "failed": "failed", "cancelled": "cancelled"}

Slot = tuple[str, str]
"""A row's place in the queue: its batch id and row id."""


def queue_order(batches: list[Batch], after: str | None) -> list[Slot]:
    """Every queued row in the order the dispatcher would start them, with
    nothing holding a listing: the batches oldest first, turned so the one
    after ``after`` (the batch served last) leads, then their queued rows
    dealt out one per batch in turn."""
    ordered = sorted(batches, key=lambda b: (b.created_at, b.id))
    ids = [b.id for b in ordered]
    if after in ids:
        turn = ids.index(after) + 1
        ordered = ordered[turn:] + ordered[:turn]
    lanes = [[(b.id, row.id) for row in b.rows if row.ai == "queued"] for b in ordered]
    order: list[Slot] = []
    for depth in range(max((len(lane) for lane in lanes), default=0)):
        order.extend(lane[depth] for lane in lanes if depth < len(lane))
    return order


class BatchQueue:
    def __init__(
        self,
        *,
        workspace: Workspace,
        batches: BatchStore,
        registry: AiRunRegistry,
        runner: AiRunner,
    ) -> None:
        self._workspace = workspace
        self._batches = batches
        self._registry = registry
        self._runner = runner
        self._wake = threading.Condition()
        self._woken = False
        self._stopping = False
        self._idle = threading.Event()
        self._idle.set()
        self._thread: threading.Thread | None = None
        self._state = threading.Lock()
        self._runs: dict[str, Slot] = {}
        """Batch runs this queue started, by run id, until they finish."""
        self._last: str | None = None
        registry.subscribe(self._finished)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Return interrupted rows to the queue, then start dispatching."""
        for batch in self._batches.all():
            self._update(batch.id, lambda row: row.ai == "running", ai="queued")
        self._thread = threading.Thread(target=self._loop, name="batch-queue", daemon=True)
        self._thread.start()
        self.wake()

    def stop(self, *, timeout: float = 10.0) -> None:
        """Start nothing more. Runs already going are the runner's to stop."""
        with self._wake:
            self._stopping = True
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def wake(self) -> None:
        """Something changed: look at the queue again."""
        with self._wake:
            self._woken = True
            self._idle.clear()
            self._wake.notify_all()

    def wait_idle(self, *, timeout: float) -> bool:
        """Block until the dispatcher has answered every wake so far. What a
        test waits on instead of a sleep; ``False`` on timeout."""
        return self._idle.wait(timeout)

    def _loop(self) -> None:
        while True:
            with self._wake:
                self._wake.wait_for(lambda: self._woken or self._stopping)
                if self._stopping:
                    self._idle.set()
                    return
                self._woken = False
            try:
                self.dispatch()
            except Exception:
                logger.exception("the batch queue's dispatch failed")
            with self._wake:
                if not self._woken:
                    self._idle.set()

    # ------------------------------------------------------------- dispatch

    def _limit(self) -> int:
        try:
            return self._workspace.load_settings().batch_ai.concurrency
        except ConfigLoadError as exc:
            logger.warning("settings.yaml is unreadable, so batch AI runs one at a time: %s", exc)
            return 1

    def _running(self) -> int:
        return sum(1 for run in self._registry.active() if run.origin == "batch")

    def dispatch(self) -> None:
        """One round: start queued rows until the limit is reached or none
        can start."""
        skipped: set[Slot] = set()
        while self._running() < self._limit():
            with self._state:
                after = self._last
            order = [
                slot for slot in queue_order(self._batches.all(), after) if slot not in skipped
            ]
            if not order:
                return
            slot = order[0]
            if not self._claim(slot):
                skipped.add(slot)

    def _claim(self, slot: Slot) -> bool:
        """Start ``slot``'s run, or say why not: the row moved on, or a
        manual run holds its listing."""
        batch_id, row_id = slot
        with self._batches.lock(batch_id):
            batch = self._batches.load(batch_id)
            row = _row(batch, row_id)
            if batch is None or row is None or row.ai != "queued":
                return False
            run = self._registry.create(
                row.name, draft_brief=self._brief_is_empty(row.name), origin="batch"
            )
            if not isinstance(run, AiRun):
                # A manual run holds the listing, or a deploy does: a
                # row Retry queued mid-deploy starts once the deploy ends.
                return False
            with self._state:
                self._runs[run.id] = slot
                self._last = batch_id
            _replace(batch, row.model_copy(update={"ai": "running", "ai_error": None}))
            self._batches.save(batch)
        self._runner.start(run)
        return True

    def _brief_is_empty(self, name: str) -> bool:
        """ADR-0048: a brief already there -- the seller's, or a retried row's own
        -- is kept, and only research and SEO rerun. The runner checks again
        under the write lock before it writes."""
        try:
            return not self._workspace.load_listing(name).brief.strip()
        except Exception:  # the run fails on the listing, with its own message
            return True

    def _finished(self, run: AiRun) -> None:
        """A run ended. A batch run's row takes its outcome; any run ending
        can free a listing or a slot, so the queue looks again."""
        with self._state:
            slot = self._runs.pop(run.id, None)
        if slot is not None and run.stop_reason != "shutdown":
            last = run.events[-1] if run.events else None
            message = last.message if isinstance(last, AiPhaseEvent) else None
            ended = _ENDED[run.phase]
            if self._registry.deploying(run.listing):
                ended = "cancelled_by_deploy"
            self._update(
                slot[0],
                lambda row: row.id == slot[1] and row.ai == "running",
                ai=ended,
                ai_error=message if ended == "failed" else None,
                ai_steps=[AiStep(**step.model_dump()) for step in run.steps],
            )
        self.wake()

    # ------------------------------------------------------ seller controls

    def cancel(self, batch_id: str) -> Batch | None:
        """**Cancel batch** (spec, *Cancellation and deletion*): queued rows
        become ``stopped``; running ones are asked to stop and end
        ``cancelled``. Written briefs and proposals stay."""
        # Under the batch's lock, so the dispatcher cannot start a row
        # between the two steps: every run it has started is in `_runs`.
        with self._batches.lock(batch_id):
            batch = self._update_locked(batch_id, lambda row: row.ai == "queued", ai="stopped")
            with self._state:
                stopping = [run for run, slot in self._runs.items() if slot[0] == batch_id]
            for run_id in stopping:
                run = self._registry.get(run_id)
                if run is not None:
                    run.request_stop("cancelled")
        self.wake()
        return batch

    def resume(self, batch_id: str) -> Batch | None:
        """**Resume**: stopped and cancelled rows join the queue again."""
        return self._requeue(batch_id, lambda row: row.ai in RESUMABLE)

    def retry(self, batch_id: str, row_id: str | None = None) -> Batch | None:
        """Retry one row's AI, or every failed row's (UI doc §7). The saved
        brief is kept, so a row that failed after drafting reruns only
        research and SEO."""
        if row_id is None:
            return self._requeue(batch_id, lambda row: row.ai == "failed")
        return self._requeue(batch_id, lambda row: row.id == row_id and row.ai in RETRYABLE)

    def _requeue(self, batch_id: str, which: Callable[[BatchRow], bool]) -> Batch | None:
        # a deleted listing's row is never queued again, by Resume or
        # by Retry -- there is no listing left to draft.
        batch = self._update(
            batch_id,
            lambda row: not row.deleted and which(row),
            ai="queued",
            ai_error=None,
            ai_steps=[],
        )
        self.wake()
        return batch

    # --------------------------------------------------------------- deploys

    @contextmanager
    def yield_to_deploy(self, listings: Sequence[str]) -> Iterator[None]:
        """ADR-0050: a UI deploy (plan or apply) takes ``listings`` from AI work
        for as long as the ``with`` lasts (spec, *Deployment interaction*).

        On entry no new run may start for them -- manual or batch; ``POST
        /api/ai/runs`` answers ``deploying`` -- their queued rows become
        ``cancelled_by_deploy``, every run still going on them, batch or
        manual, is asked to stop, and this waits until each has finished
        and its row has its outcome. Only then does the deploy read a
        listing. On exit the listings are free again and the queue looks
        again, for a row the seller retried meanwhile.

        The runs are waited for without a limit of their own: a stop kills
        a provider's process tree and research starts no new call, and the
        runner's watchdog bounds any run to ``runner.RUN_LIMIT_SECONDS``.
        """
        names = list(listings)
        # Holding first means every run the dispatcher could still start
        # for these listings is either in `active` or refused.
        active = self._registry.hold_for_deploy(names)
        try:
            keys = {name.casefold() for name in names}
            for batch in self._batches.all():
                self._update(
                    batch.id,
                    lambda row: row.name.casefold() in keys and row.ai == "queued",
                    ai="cancelled_by_deploy",
                )
            for run in active:
                run.request_stop("deploy")
            for run in active:
                run.wait_settled()
            yield
        finally:
            self._registry.release_deploy(names)
            self.wake()

    # ------------------------------------------------------------- reading

    def pending(self, listing: str) -> bool:
        """Does batch work own ``listing``'s AI right now?"""
        key = listing.casefold()
        return any(
            row.name.casefold() == key and row.ai in PENDING
            for batch in self._batches.all()
            for row in batch.rows
        )

    def order(self) -> list[Slot]:
        """The queued rows in the order they will start."""
        with self._state:
            after = self._last
        return queue_order(self._batches.all(), after)

    def concurrency(self) -> int:
        return self._limit()

    # -------------------------------------------------------------- helpers

    def _update(
        self, batch_id: str, which: Callable[[BatchRow], bool], **changes: object
    ) -> Batch | None:
        with self._batches.lock(batch_id):
            return self._update_locked(batch_id, which, **changes)

    def _update_locked(
        self, batch_id: str, which: Callable[[BatchRow], bool], **changes: object
    ) -> Batch | None:
        batch = self._batches.load(batch_id)
        if batch is None:
            return None
        matching = [row for row in batch.rows if which(row)]
        for row in matching:
            _replace(batch, row.model_copy(update=changes))
        if matching:
            self._batches.save(batch)
        return batch


def _row(batch: Batch | None, row_id: str) -> BatchRow | None:
    return next((row for row in batch.rows if row.id == row_id), None) if batch else None


def _replace(batch: Batch, row: BatchRow) -> None:
    batch.rows[:] = [row if r.id == row.id else r for r in batch.rows]

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from etsy_listings.core.application.ai.events import AiPhaseEvent
from etsy_listings.core.application.ai.readiness import (
    AiReadinessBlock,
    batch_blocked,
    current_providers,
)
from etsy_listings.core.application.ai.registry import (
    AiRun,
    AiRunRegistry,
    Conflict,
    Deploying,
)
from etsy_listings.core.application.ai.runner import AiRunner
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.batches import RETRYABLE, AiState, AiStep, Batch, BatchRow, BatchStore
from etsy_listings.core.config.settings import SettingsProblem
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

PENDING: frozenset[AiState] = frozenset({"queued", "running"})
"""A row in either state owns its listing's AI: the manual control is
refused while one exists (spec, *Scheduling*)."""

RESUMABLE: frozenset[AiState] = frozenset({"stopped", "cancelled"})
"""Not ``cancelled_by_deploy``: work a deploy cancelled must not resume onto
the deployed listing (ADR-0050; spec, *Deployment interaction*)."""

_ENDED: dict[str, AiState] = {"done": "done", "failed": "failed", "cancelled": "cancelled"}

Slot = tuple[str, str]
"""A row's place in the queue: its batch id and row id."""


def queue_order(batches: list[Batch], after: str | None) -> list[Slot]:
    """Every queued row in the order the dispatcher would start them, with
    nothing holding a listing; ``after`` is the batch served last."""
    ordered = _rotated_after(sorted(batches, key=lambda b: (b.created_at, b.id)), after)
    return _round_robin([[(b.id, row.id) for row in b.rows if row.ai == "queued"] for b in ordered])


def _rotated_after(ordered: list[Batch], after: str | None) -> list[Batch]:
    ids = [b.id for b in ordered]
    if after not in ids:
        return ordered
    turn = ids.index(after) + 1
    return ordered[turn:] + ordered[:turn]


def _round_robin(lanes: list[list[Slot]]) -> list[Slot]:
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
        gate: JobGate | None = None,
    ) -> None:
        self._workspace = workspace
        self._gate = gate if gate is not None else JobGate()
        self._gate.on_resume(self.wake)
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

    def start(self) -> None:
        self._requeue_interrupted_rows()
        self._thread = threading.Thread(target=self._loop, name="batch-queue", daemon=True)
        self._thread.start()
        self.wake()

    def _requeue_interrupted_rows(self) -> None:
        for batch in self._batches.all():
            self._update(batch.id, lambda row: row.ai == "running", ai="queued")

    def stop(self, *, timeout: float = 10.0) -> None:
        """Start nothing more. Runs already going are the runner's to stop."""
        with self._wake:
            self._stopping = True
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def wake(self) -> None:
        with self._wake:
            self._woken = True
            self._idle.clear()
            self._wake.notify_all()

    def wait_idle(self, *, timeout: float) -> bool:
        """Block until the dispatcher has answered every wake so far;
        ``False`` on timeout."""
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

    def _limit(self) -> int:
        settings = self._workspace.settings_if_readable(skipping="dispatching batch rows")
        return settings.batch_ai.concurrency if settings is not None else 0

    def _running(self) -> int:
        return sum(1 for run in self._registry.active() if run.origin == "batch")

    def dispatch(self) -> None:
        skipped: set[Slot] = set()
        while not self._gate.paused and self._running() < self._limit():
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
        batch_id, row_id = slot
        with self._batches.lock(batch_id):
            batch = self._batches.load(batch_id)
            row = _row(batch, row_id)
            if batch is None or row is None or row.ai != "queued":
                return False
            # A pause since `dispatch` looked leaves the row queued and ends the round.
            ticket = self._gate.admit(f"Batch AI for {row.name}")
            if ticket is None:
                return False
            run = self._registry.create(
                row.name,
                draft_brief=self._brief_is_empty(row.name),
                origin="batch",
                ticket=ticket,
            )
            if isinstance(run, Conflict | Deploying):
                return False
            self._save_claim(batch, row, run)
            with self._state:
                self._runs[run.id] = slot
                self._last = batch_id
        self._runner.start(run)
        return True

    def _save_claim(self, batch: Batch, row: BatchRow, run: AiRun) -> None:
        try:
            _replace(batch, row.model_copy(update={"ai": "running", "ai_error": None}))
            self._batches.save(batch)
        except OSError:
            run.finish("failed", "The batch row could not be saved.")
            raise

    def _brief_is_empty(self, name: str) -> bool:
        try:
            return not self._workspace.load_listing(name).brief.strip()
        except Exception:  # noqa: BLE001 -- a listing that will not load is an empty brief; the run reports it
            return True

    def _finished(self, run: AiRun) -> None:
        with self._state:
            slot = self._runs.pop(run.id, None)
        if slot is not None and run.stop_reason != "shutdown":
            self._record_outcome(run, slot)
        self.wake()

    def _record_outcome(self, run: AiRun, slot: Slot) -> None:
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

    def cancel(self, batch_id: str) -> Batch | None:
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
        return self._requeue(batch_id, lambda row: row.ai in RESUMABLE)

    def retry(self, batch_id: str, row_id: str | None = None) -> Batch | None:
        if row_id is None:
            return self._requeue(batch_id, lambda row: row.ai == "failed")
        return self._requeue(batch_id, lambda row: row.id == row_id and row.ai in RETRYABLE)

    def _requeue(self, batch_id: str, which: Callable[[BatchRow], bool]) -> Batch | None:
        batch = self._update(
            batch_id,
            lambda row: not row.deleted and which(row),
            ai="queued",
            ai_error=None,
            ai_steps=[],
        )
        self.wake()
        return batch

    @contextmanager
    def yield_to_deploy(self, listings: Sequence[str]) -> Iterator[None]:
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

    def waiting_for_backup(self, row: BatchRow) -> bool:
        return self._gate.holds(queued=row.ai == "queued")

    def pending(self, listing: str) -> bool:
        key = listing.casefold()
        return any(
            row.name.casefold() == key and row.ai in PENDING
            for batch in self._batches.all()
            for row in batch.rows
        )

    def order(self) -> list[Slot]:
        with self._state:
            after = self._last
        return queue_order(self._batches.all(), after)

    def concurrency(self) -> int | SettingsProblem:
        settings = self._workspace.settings_or_problem()
        if isinstance(settings, SettingsProblem):
            return settings
        return settings.batch_ai.concurrency

    def blocked(self) -> AiReadinessBlock | None:
        workspace = self._workspace
        providers = current_providers(self._runner.providers, workspace)
        if isinstance(providers, SettingsProblem):
            return AiReadinessBlock(
                message=providers.message,
                remedy="Correct the named key in settings.yaml, then retry. Your staging is kept.",
            )
        return batch_blocked(workspace, providers)

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

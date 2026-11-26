from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from etsy_listings.core.application.deploy.events import (
    TERMINAL_PHASES,
    AnyRunEvent,
    ApplyRunPhase,
    PhaseEvent,
    PlanRunPhase,
    RunKind,
    RunPhase,
    RunScope,
)

_WAKE = ""
"""Queued by :meth:`RunRegistry.wake`; never a run id (ids are non-empty),
so :meth:`RunRegistry.drain_and_cancel` finds no run for it and skips it."""


@dataclass(frozen=True, kw_only=True)
class _Publishes:
    publish: bool = False
    """Publish new and still-draft listings rather than leave drafts
    (``publishing_pipeline``). Opt-in; a plan and the apply it reviews agree."""


@dataclass(frozen=True)
class ListingPlan(_Publishes):
    listings: tuple[str, ...]


@dataclass(frozen=True)
class WorkspacePlan(_Publishes):
    listings: tuple[str, ...]


@dataclass(frozen=True)
class ListingApply(_Publishes):
    listings: tuple[str, ...]
    expect: Mapping[str, str]


@dataclass(frozen=True)
class WorkspaceApply(_Publishes):
    listings: tuple[str, ...]
    expect: Mapping[str, str]
    reviewed_run_id: str


@dataclass(frozen=True)
class BatchPlan(_Publishes):
    batch_id: str
    listings: tuple[str, ...]


@dataclass(frozen=True)
class BatchApply(_Publishes):
    batch_id: str
    listings: tuple[str, ...]
    expect: Mapping[str, str]
    reviewed_run_id: str


RunCommand = ListingPlan | WorkspacePlan | BatchPlan | ListingApply | WorkspaceApply | BatchApply
ReviewedApply = WorkspaceApply | BatchApply
"""An apply that must repeat a reviewed plan of its own scope (``review``)."""


@dataclass
class PlanRunState:
    phase: PlanRunPhase = "queued"
    cancel_requested: bool = False


@dataclass
class ApplyRunState:
    phase: ApplyRunPhase = "queued"


@dataclass
class Run:
    """One plan or apply run: its scope, identity, listings, and event log.

    A workspace apply keeps ``reviewed_run_id`` so a client can replay the
    completed review alongside the apply events; the registry deliberately
    retains that source run until a later workspace run supersedes it.

    The :class:`threading.Condition` is what bridges the worker thread (which
    appends events) and the SSE route's async generator (which waits for
    them) without a new dependency -- see ``server/api/runs.py``'s own docstring for
    the bridge itself; this class only owns the lock and the notifying.
    """

    id: str
    command: RunCommand
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    events: list[AnyRunEvent] = field(default_factory=list)
    seen: bool = False
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    _next_event_id: int = field(default=1, repr=False)
    _state: PlanRunState | ApplyRunState = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """The starting ``queued`` phase is itself the run's first event --
        a client that opens the SSE stream from event 0 sees the same phase
        history whether it connected before or after the worker thread ever
        looked at this run."""

        self._state = (
            PlanRunState()
            if isinstance(self.command, ListingPlan | WorkspacePlan | BatchPlan)
            else ApplyRunState()
        )
        self.events.append(PhaseEvent(id=self._next_event_id, phase="queued"))
        self._next_event_id += 1

    @property
    def kind(self) -> RunKind:
        return (
            "plan" if isinstance(self.command, ListingPlan | WorkspacePlan | BatchPlan) else "apply"
        )

    @property
    def scope(self) -> RunScope:
        if isinstance(self.command, WorkspacePlan | WorkspaceApply):
            return "workspace"
        if isinstance(self.command, BatchPlan | BatchApply):
            return "batch"
        return "listings"

    @property
    def batch_id(self) -> str | None:
        return self.command.batch_id if isinstance(self.command, BatchPlan | BatchApply) else None

    @property
    def listings(self) -> tuple[str, ...]:
        return self.command.listings

    @property
    def expect(self) -> Mapping[str, str] | None:
        if isinstance(self.command, ListingApply | WorkspaceApply | BatchApply):
            return self.command.expect
        return None

    @property
    def publish(self) -> bool:
        return self.command.publish

    @property
    def reviewed_run_id(self) -> str | None:
        if isinstance(self.command, WorkspaceApply | BatchApply):
            return self.command.reviewed_run_id
        return None

    @property
    def phase(self) -> RunPhase:
        return self._state.phase

    @property
    def plan_phase(self) -> PlanRunPhase:
        if not isinstance(self._state, PlanRunState):
            raise TypeError("an apply run has no plan phase")
        return self._state.phase

    @property
    def apply_phase(self) -> ApplyRunPhase:
        if not isinstance(self._state, ApplyRunState):
            raise TypeError("a plan run has no apply phase")
        return self._state.phase

    @property
    def cancel_requested(self) -> bool:
        return self._state.cancel_requested if isinstance(self._state, PlanRunState) else False

    def append(self, make_event: Callable[[int], AnyRunEvent]) -> AnyRunEvent:
        """Append one event, its ``id`` assigned under the same lock a waiter
        reads with -- ``make_event`` takes the id rather than this returning
        one to stamp in, so a caller can never construct an event with an id
        that turns out to already be taken by the time it is appended."""
        with self.condition:
            event = make_event(self._next_event_id)
            self._next_event_id += 1
            self.events.append(event)
            self.condition.notify_all()
            return event

    def transition_plan(self, phase: PlanRunPhase) -> None:
        if not isinstance(self._state, PlanRunState):
            raise TypeError("an apply run cannot enter a plan phase")

        with self.condition:
            event = PhaseEvent(id=self._next_event_id, phase=phase)
            self._next_event_id += 1
            self.events.append(event)
            self._state.phase = phase
            self.condition.notify_all()

    def transition_apply(self, phase: ApplyRunPhase) -> None:
        if not isinstance(self._state, ApplyRunState):
            raise TypeError("a plan run cannot enter an apply phase")

        with self.condition:
            event = PhaseEvent(id=self._next_event_id, phase=phase)
            self._next_event_id += 1
            self.events.append(event)
            self._state.phase = phase
            self.condition.notify_all()

    def request_cancel(self) -> None:
        if not isinstance(self._state, PlanRunState):
            raise TypeError("an apply run cannot be cancelled")
        self._state.cancel_requested = True

    def mark_seen(self) -> None:
        with self.condition:
            self.seen = True

    def wait_for_events(self, after_id: int, *, timeout: float) -> tuple[list[AnyRunEvent], bool]:
        """Block up to ``timeout`` seconds for an event past ``after_id``.

        Returns ``(pending, done)``. ``done`` is true only once the run has
        reached a terminal phase *and* every event up to that phase has
        already been returned -- so a caller that loops on this until ``done``
        is guaranteed to see every event exactly once, in order, with nothing
        dropped between one call and the next (``server/api/runs.py``'s SSE loop is
        that caller). A short ``timeout`` rather than an unbounded wait is
        what lets that same loop notice the surrounding server is shutting
        down without this class knowing anything about shutdown.
        """
        with self.condition:
            pending = [e for e in self.events if e.id > after_id]
            if not pending and self.phase not in TERMINAL_PHASES:
                self.condition.wait(timeout=timeout)
                pending = [e for e in self.events if e.id > after_id]
            done = not pending and self.phase in TERMINAL_PHASES
            return pending, done


def abandon(run: Run) -> None:
    if run.phase in TERMINAL_PHASES:
        return
    if run.kind == "plan":
        run.transition_plan("cancelled")
    else:
        run.transition_apply("failed")


@dataclass(frozen=True)
class Conflict:
    active_run: str


@dataclass
class RunRegistry:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _runs: dict[str, Run] = field(default_factory=dict)
    _holder: dict[str, str] = field(default_factory=dict)
    _workspace_holder: str | None = None
    _batch_holder: dict[str, str] = field(default_factory=dict)
    _queue: queue.Queue[str] = field(default_factory=queue.Queue)
    _id_source: Callable[[], str] = field(default=lambda: uuid.uuid4().hex)

    def create(self, command: RunCommand) -> Run | Conflict:
        with self._lock:
            blocking = self._blocking_run(command)
            if blocking is not None:
                return Conflict(active_run=blocking.id)
            run = Run(id=self._id_source(), command=command)
            self._runs[run.id] = run
            if run.scope == "workspace":
                self._workspace_holder = run.id
            elif run.batch_id is not None:
                self._batch_holder[run.batch_id] = run.id
            else:
                for name in run.listings:
                    self._holder[name] = run.id
            self._queue.put(run.id)
            return run

    def _blocking_run(self, command: RunCommand) -> Run | None:
        blocking = self._active(self._workspace_holder or "")
        if blocking is not None:
            return blocking
        if isinstance(command, WorkspacePlan | WorkspaceApply):
            holder_ids: Iterable[str] = [*self._holder.values(), *self._batch_holder.values()]
            return next((run for run in map(self._active, holder_ids) if run is not None), None)
        wanted = set(command.listings)
        holder_ids = [
            *(self._holder.get(name, "") for name in command.listings),
            *self._batch_holder.values(),
        ]
        return next(
            (
                run
                for run in map(self._active, holder_ids)
                if run is not None and wanted.intersection(run.listings)
            ),
            None,
        )

    def _active(self, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        return run if run is not None and run.phase not in TERMINAL_PHASES else None

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def all_runs(self) -> list[Run]:
        with self._lock:
            return list(self._runs.values())

    def for_listing(self, name: str) -> Run | None:
        with self._lock:
            return self._runs.get(self._holder.get(name, ""))

    def for_workspace(self) -> Run | None:
        with self._lock:
            return self._runs.get(self._workspace_holder or "")

    def for_batch(self, batch_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(self._batch_holder.get(batch_id, ""))

    def for_scope(self, scope: RunScope) -> list[Run]:
        with self._lock:
            return [run for run in self._runs.values() if run.scope == scope]

    def dequeue(self, *, timeout: float) -> str | None:
        """The next queued run id, for the executor's worker thread. ``None``
        on a timeout or a :meth:`wake`, which is what lets that thread notice
        a stop flag without blocking on this forever."""
        try:
            run_id = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return None if run_id == _WAKE else run_id

    def wake(self) -> None:
        self._queue.put(_WAKE)

    def drain_and_cancel(self) -> None:
        """Every run still sitting in the queue reaches a legal terminal state
        without running: plan runs are cancelled and apply runs fail.
        Whichever of this and the worker thread's own ``dequeue`` reaches a
        given id first wins it outright (``queue.Queue`` hands each item to
        exactly one caller), so there is no run this could cancel out from
        under the thread already executing it.
        """
        while True:
            try:
                run_id = self._queue.get_nowait()
            except queue.Empty:
                return
            run = self.get(run_id)
            if run is not None:
                abandon(run)

    def cancel(self, run_id: str) -> bool | None:
        """Cancel a queued or running **plan**.

        ``None``: no such run. ``False``: it exists but cannot be cancelled --
        it is an ``apply`` (refused unconditionally, decision 8: Back leaves,
        it never cancels one), or it has already reached a terminal phase.
        ``True``: cancelled outright (it was only ``queued``, so this
        transitions it immediately) or asked to stop (``planning``/
        ``previewing``, where only the worker thread actually executing it can
        observe :attr:`Run.cancel_requested` and act on it at its next
        boundary -- see ``executor.py``).
        """
        run = self.get(run_id)
        if run is None:
            return None
        if run.kind == "apply" or run.phase in TERMINAL_PHASES:
            return False
        run.request_cancel()
        if run.phase == "queued":
            run.transition_plan("cancelled")
        return True

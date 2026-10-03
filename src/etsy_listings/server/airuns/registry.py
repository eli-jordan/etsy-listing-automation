"""``AiRun`` and the registry of them, in memory (features/market-seo-20260924/spec.md, *AI runs*).

One active run per listing: a second ``create`` while one is running is a
:class:`Conflict` naming it. A finished run stays the listing's latest until
the next run replaces it, and is then forgotten. Nothing survives a restart.

Unlike ``server/runs``, nothing here is queued: every run gets its own thread
(``runner.py``), so the registry only answers who holds a listing. Listing
names are compared case-insensitively, as the write locks compare them.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from etsy_listings.server.airuns.events import (
    STEP_IDS,
    AiPhaseEvent,
    AiRunPhase,
    AiStepEvent,
    AnyAiRunEvent,
    StepId,
    StepState,
    TerminalPhase,
    WorkflowStep,
)

StopReason = Literal["cancelled", "timeout", "shutdown", "deploy"]
"""Why a run was asked to stop. ``deploy`` is a UI deploy taking the listing
: the run ends ``cancelled`` like any other stop, and a batch row it
belonged to becomes ``cancelled_by_deploy`` rather than ``cancelled``."""
RunOrigin = Literal["manual", "batch"]
"""Who started the run: the editor's AI Mode, or the batch queue. A
batch run is otherwise an ordinary run -- same chain, same limit."""
FinishListener = Callable[["AiRun"], None]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(eq=False)
class AiRun:
    """One run: its listing, its event buffer, and the cancel event every
    provider call and the market research share.

    The :class:`threading.Condition` bridges the run's thread, which appends,
    and the SSE route, which waits (``api/airuns.py``).
    """

    id: str
    listing: str
    draft_brief: bool
    origin: RunOrigin = "manual"
    created_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    events: list[AnyAiRunEvent] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    stop_reason: StopReason | None = None
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    on_finish: tuple[FinishListener, ...] = field(default=(), repr=False)
    """Called once the run has finished, on the thread that finished it and
    outside ``condition`` -- a listener takes other locks (the batch
    store's), and a request holding one of those may be reading this run."""
    _settled: threading.Event = field(default_factory=threading.Event, repr=False)
    """Set once :meth:`finish` has told every listener: a batch row has its
    outcome by then, not just the run its phase."""
    _phase: AiRunPhase = "running"
    _steps: dict[StepId, WorkflowStep] = field(
        default_factory=lambda: {i: WorkflowStep(id=i, state="pending") for i in STEP_IDS}
    )

    @property
    def phase(self) -> AiRunPhase:
        return self._phase

    @property
    def finished(self) -> bool:
        return self._phase != "running"

    @property
    def steps(self) -> list[WorkflowStep]:
        with self.condition:
            return [self._steps[i] for i in STEP_IDS]

    @property
    def active_step(self) -> StepId | None:
        with self.condition:
            return next((i for i in STEP_IDS if self._steps[i].state == "active"), None)

    def emit(self, make_event: Callable[[int], AnyAiRunEvent]) -> None:
        """Append one event, numbered under the lock a waiter reads with."""
        with self.condition:
            event = make_event(len(self.events) + 1)
            self.events.append(event)
            if isinstance(event, AiStepEvent):
                self._steps[event.id] = WorkflowStep(
                    id=event.id, state=event.state, detail=event.detail
                )
            self.condition.notify_all()

    def step(self, step: StepId, state: StepState, detail: str | None = None) -> None:
        self.emit(lambda seq: AiStepEvent(seq=seq, id=step, state=state, detail=detail))

    def finish(self, phase: TerminalPhase, message: str | None = None) -> None:
        """Emit the terminal ``phase`` event, then tell the listeners. Only
        the first call counts."""
        with self.condition:
            if self.finished:
                return
            self.emit(lambda seq: AiPhaseEvent(seq=seq, phase=phase, message=message))
            self._phase = phase
            self.finished_at = _now()
        try:
            for listener in self.on_finish:
                listener(self)
        finally:
            self._settled.set()

    def wait_settled(self, timeout: float | None = None) -> bool:
        """Block until the run has finished and its listeners have heard.
        ``False`` on timeout."""
        return self._settled.wait(timeout)

    def request_stop(self, reason: StopReason) -> bool:
        """Ask the run to stop: sets the cancel event, which kills a provider's
        subprocess tree and stops research at its next call. ``False`` when
        the run has already finished. The first reason wins."""
        with self.condition:
            if self.finished:
                return False
            if self.stop_reason is None:
                self.stop_reason = reason
            self.cancel_event.set()
            return True

    def wait_for_events(
        self, after_seq: int, *, timeout: float
    ) -> tuple[list[AnyAiRunEvent], bool]:
        """Block up to ``timeout`` seconds for events past ``after_seq``.
        ``done`` is true once the run has finished and every event has been
        returned -- ``server/runs``' contract, so the SSE loop is the same."""
        with self.condition:
            pending = self.events[after_seq:]
            if not pending and not self.finished:
                self.condition.wait(timeout=timeout)
                pending = self.events[after_seq:]
            return pending, not pending and self.finished


@dataclass(frozen=True)
class Conflict:
    """``create`` refused: ``active_run`` already holds the listing."""

    active_run: str


@dataclass(frozen=True)
class Deploying:
    """``create`` refused: a UI deploy holds the listing."""


class AiRunRegistry:
    def __init__(self, *, id_source: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, AiRun] = {}
        self._latest: dict[str, str] = {}
        self._id_source = id_source
        self._listeners: list[FinishListener] = []
        self._deploying: Counter[str] = Counter()

    def subscribe(self, listener: FinishListener) -> None:
        """Hear every run this registry creates from now on finish -- the
        batch queue's wake-up, and how its rows learn their outcome."""
        with self._lock:
            self._listeners.append(listener)

    def create(
        self, listing: str, *, draft_brief: bool, origin: RunOrigin = "manual"
    ) -> AiRun | Conflict | Deploying:
        key = listing.casefold()
        with self._lock:
            if self._deploying[key]:
                return Deploying()
            previous = self._runs.get(self._latest.get(key, ""))
            if previous is not None:
                if not previous.finished:
                    return Conflict(active_run=previous.id)
                del self._runs[previous.id]
            run = AiRun(
                id=self._id_source(),
                listing=listing,
                draft_brief=draft_brief,
                origin=origin,
                on_finish=tuple(self._listeners),
            )
            self._runs[run.id] = run
            self._latest[key] = run.id
            return run

    def get(self, run_id: str) -> AiRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def latest(self, listing: str) -> AiRun | None:
        """The listing's running or most recent run."""
        with self._lock:
            return self._runs.get(self._latest.get(listing.casefold(), ""))

    def forget(self, listing: str) -> None:
        """Drop the listing's finished run: the listing was deleted or
        renamed, so a new listing given that name must not reattach to it
        and replay a brief and proposal that belong to another. A running
        run is left to end on its own -- it fails once the listing is gone."""
        key = listing.casefold()
        with self._lock:
            run = self._runs.get(self._latest.get(key, ""))
            if run is not None and run.finished:
                del self._runs[run.id]
                del self._latest[key]

    def active(self) -> list[AiRun]:
        with self._lock:
            return [run for run in self._runs.values() if not run.finished]

    # ------------------------------------------------------------ deploys

    def hold_for_deploy(self, listings: Iterable[str]) -> list[AiRun]:
        """ADR-0050: refuse every new run for ``listings`` until
        :meth:`release_deploy`, and answer the runs still going on them --
        in one step, so no run can start between the two. Counted, so two
        holds on one listing need two releases."""
        keys = {name.casefold() for name in listings}
        with self._lock:
            self._deploying.update(keys)
            return [
                run
                for run in self._runs.values()
                if not run.finished and run.listing.casefold() in keys
            ]

    def release_deploy(self, listings: Iterable[str]) -> None:
        keys = {name.casefold() for name in listings}
        with self._lock:
            self._deploying.subtract(keys)
            self._deploying += Counter()  # drop the zeroes

    def deploying(self, listing: str) -> bool:
        with self._lock:
            return self._deploying[listing.casefold()] > 0

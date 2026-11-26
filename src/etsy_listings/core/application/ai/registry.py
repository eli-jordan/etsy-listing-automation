"""``AiRun`` and the in-memory registry answering which run holds a listing.

Listing names compare case-insensitively, as the write locks compare them."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from etsy_listings.core.application.ai.events import (
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
from etsy_listings.core.application.job_gate import Ticket

StopReason = Literal["cancelled", "timeout", "shutdown", "deploy"]
"""Why a run was asked to stop. ``deploy`` is a UI deploy taking the listing
: the run ends ``cancelled`` like any other stop, and a batch row it
belonged to becomes ``cancelled_by_deploy`` rather than ``cancelled``."""
RunOrigin = Literal["manual", "batch"]
"""Who started the run: the editor's AI Mode, or the batch queue. A
batch run stops after the brief; manual AI Mode continues through research
and SEO. Both share the run's cancellation and time limit."""
FinishListener = Callable[["AiRun"], None]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(eq=False)
class AiRun:
    """``condition`` is the lock the run's thread appends under and the SSE
    route waits on."""

    id: str
    listing: str
    draft_brief: bool
    origin: RunOrigin = "manual"
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    events: list[AnyAiRunEvent] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    stop_reason: StopReason | None = None
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    on_finish: tuple[FinishListener, ...] = field(default=(), repr=False)
    """Called outside ``condition``: a listener takes the batch store's lock,
    and a request holding that may be reading this run."""
    _settled: threading.Event = field(default_factory=threading.Event, repr=False)
    _phase: AiRunPhase = "running"
    _ticket: Ticket | None = field(default=None, repr=False)
    """Released only after every listener has run, so a backup waiting for
    quiet starts after a batch row has its outcome."""
    _steps: dict[StepId, WorkflowStep] = field(
        default_factory=lambda: {i: WorkflowStep(id=i, state="pending") for i in STEP_IDS}
    )

    def __post_init__(self) -> None:
        if self._phase == "running" and self.started_at is None:
            self.started_at = self.created_at

    @property
    def phase(self) -> AiRunPhase:
        return self._phase

    @property
    def finished(self) -> bool:
        return self._phase not in ("queued", "running")

    def begin(self, ticket: Ticket) -> bool:
        with self.condition:
            if self._phase == "queued":
                self._phase = "running"
                self.started_at = _now()
                self._ticket = ticket
                return True
        ticket.release()
        return False

    @property
    def steps(self) -> list[WorkflowStep]:
        with self.condition:
            return [self._steps[i] for i in STEP_IDS]

    @property
    def active_step(self) -> StepId | None:
        with self.condition:
            return next((i for i in STEP_IDS if self._steps[i].state == "active"), None)

    def emit(self, make_event: Callable[[int], AnyAiRunEvent]) -> None:
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
            if self._ticket is not None:
                self._ticket.release()

    def fail_unless_finished(self, message: str) -> None:
        self.finish("failed", message)

    def wait_settled(self, timeout: float | None = None) -> bool:
        return self._settled.wait(timeout)

    def request_stop(self, reason: StopReason) -> bool:
        """A run held by a backup's pause has no thread to notice the cancel
        event, so it ends here."""
        with self.condition:
            if self.finished:
                return False
            if self.stop_reason is None:
                self.stop_reason = reason
            self.cancel_event.set()
            held = self._phase == "queued"
        if held:
            self.finish("cancelled")
        return True

    def wait_for_events(
        self, after_seq: int, *, timeout: float
    ) -> tuple[list[AnyAiRunEvent], bool]:
        with self.condition:
            pending = self.events[after_seq:]
            if not pending and not self.finished:
                self.condition.wait(timeout=timeout)
                pending = self.events[after_seq:]
            return pending, not pending and self.finished


@dataclass(frozen=True)
class Conflict:
    active_run: str


@dataclass(frozen=True)
class Deploying: ...


class AiRunRegistry:
    def __init__(self, *, id_source: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, AiRun] = {}
        self._latest: dict[str, str] = {}
        self._id_source = id_source
        self._listeners: list[FinishListener] = []
        self._deploying: Counter[str] = Counter()

    def subscribe(self, listener: FinishListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def create(
        self,
        listing: str,
        *,
        draft_brief: bool,
        origin: RunOrigin = "manual",
        queued: bool = False,
        ticket: Ticket | None = None,
    ) -> AiRun | Conflict | Deploying:
        """The run owns ``ticket``; a refusal releases it."""
        key = listing.casefold()
        with self._lock:
            refused = self._refusal_locked(key)
            if refused is not None:
                if ticket is not None:
                    ticket.release()
                return refused
            previous = self._runs.get(self._latest.get(key, ""))
            if previous is not None:
                del self._runs[previous.id]
            run = AiRun(
                id=self._id_source(),
                listing=listing,
                draft_brief=draft_brief,
                origin=origin,
                on_finish=tuple(self._listeners),
                _phase="queued" if queued else "running",
                _ticket=ticket,
            )
            self._runs[run.id] = run
            self._latest[key] = run.id
            return run

    def _refusal_locked(self, key: str) -> Conflict | Deploying | None:
        if self._deploying[key]:
            return Deploying()
        previous = self._runs.get(self._latest.get(key, ""))
        if previous is not None and not previous.finished:
            return Conflict(active_run=previous.id)
        return None

    def get(self, run_id: str) -> AiRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def latest(self, listing: str) -> AiRun | None:
        with self._lock:
            return self._runs.get(self._latest.get(listing.casefold(), ""))

    def forget(self, listing: str) -> None:
        """So a new listing given a deleted or renamed one's name cannot
        reattach to its finished run and replay its brief and proposal."""
        key = listing.casefold()
        with self._lock:
            run = self._runs.get(self._latest.get(key, ""))
            if run is not None and run.finished:
                del self._runs[run.id]
                del self._latest[key]

    def active(self) -> list[AiRun]:
        with self._lock:
            return [run for run in self._runs.values() if not run.finished]

    def hold_for_deploy(self, listings: Iterable[str]) -> list[AiRun]:
        """Refuses new runs for ``listings`` and answers the active ones in one
        step, so no run can start between the two (ADR-0050)."""
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
            for key in keys:
                self._deploying[key] -= 1
                if self._deploying[key] <= 0:
                    del self._deploying[key]

    def deploying(self, listing: str) -> bool:
        with self._lock:
            return self._deploying[listing.casefold()] > 0

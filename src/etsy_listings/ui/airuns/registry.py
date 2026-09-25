"""``AiRun`` and the registry of them, in memory (market-seo.md, *AI runs*).

One active run per listing: a second ``create`` while one is running is a
:class:`Conflict` naming it. A finished run stays the listing's latest until
the next run replaces it, and is then forgotten. Nothing survives a restart.

Unlike ``ui/runs``, nothing here is queued: every run gets its own thread
(``runner.py``), so the registry only answers who holds a listing. Listing
names are compared case-insensitively, as the write locks compare them.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from etsy_listings.ui.airuns.events import (
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

StopReason = Literal["cancelled", "timeout", "shutdown"]


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
    created_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    events: list[AnyAiRunEvent] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    stop_reason: StopReason | None = None
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
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
        """Emit the terminal ``phase`` event. Only the first call counts."""
        with self.condition:
            if self.finished:
                return
            self.emit(lambda seq: AiPhaseEvent(seq=seq, phase=phase, message=message))
            self._phase = phase
            self.finished_at = _now()

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
        returned -- ``ui/runs``' contract, so the SSE loop is the same."""
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


class AiRunRegistry:
    def __init__(self, *, id_source: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, AiRun] = {}
        self._latest: dict[str, str] = {}
        self._id_source = id_source

    def create(self, listing: str, *, draft_brief: bool) -> AiRun | Conflict:
        key = listing.casefold()
        with self._lock:
            previous = self._runs.get(self._latest.get(key, ""))
            if previous is not None:
                if not previous.finished:
                    return Conflict(active_run=previous.id)
                del self._runs[previous.id]
            run = AiRun(id=self._id_source(), listing=listing, draft_brief=draft_brief)
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

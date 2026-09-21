"""``Run``, and the registry that owns which listings or workspace are held by
which run (A33/A34, decision 7).

A run is in-memory only -- "Runs are in memory only, so a restart forgets
them, and history stays Phase 6's ``runs/`` SQLite recorder" -- so this module
is a handful of ``dict``s guarded by one lock, not a store.

**Locking is a conflict check, not a mutex.** The one thing that actually
serialises writes is the single FIFO worker thread in ``executor.py`` -- two
runs for two different listings can never execute concurrently no matter what
this module does, because there is only one thread to execute either of them.
What this module answers is a different question: *may a new run for this
listing be **queued** at all*, so the editor gets an immediate ``409`` naming
the run already in flight (to reattach to) rather than a run that silently
waits behind it forever, or two runs that both believe they own one listing's
lockfile.

**Retention falls out of the same mapping, for free.** "A finished run is
kept until the next run for any of its listings is created" turns out to need
no separate cleanup pass: :attr:`RunRegistry._holder` always points a listing
at its most recent run, whether that run is still going or long finished, and
:meth:`RunRegistry.create` only refuses when the current holder is *not yet
terminal*. Creating a new run for a listing simply overwrites the pointer --
the old, finished ``Run`` is still sitting in :attr:`RunRegistry._runs` and
answers ``GET /api/runs/{id}`` if anyone still has that id, but
``GET /api/runs?listing=`` has already moved on, which is the whole of what
"kept until superseded" means.
"""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from etsy_listings.ui.runs.events import (
    TERMINAL_PHASES,
    AnyRunEvent,
    RunKind,
    RunPhase,
    RunScope,
)


@dataclass
class Run:
    """One plan or apply run: its scope, identity, listings, and event log.

    A workspace apply keeps ``reviewed_run_id`` so a client can replay the
    completed review alongside the apply events; the registry deliberately
    retains that source run until a later workspace run supersedes it (A34).

    The :class:`threading.Condition` is what bridges the worker thread (which
    appends events) and the SSE route's async generator (which waits for
    them) without a new dependency -- see ``api/runs.py``'s own docstring for
    the bridge itself; this class only owns the lock and the notifying.
    """

    id: str
    kind: RunKind
    listings: tuple[str, ...]
    expect: Mapping[str, str] | None = None
    scope: RunScope = "listings"
    reviewed_run_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    phase: RunPhase = "queued"
    events: list[AnyRunEvent] = field(default_factory=list)
    seen: bool = False
    cancel_requested: bool = False
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)
    _next_event_id: int = field(default=1, repr=False)

    def __post_init__(self) -> None:
        """The starting ``queued`` phase is itself the run's first event --
        a client that opens the SSE stream from event 0 sees the same phase
        history whether it connected before or after the worker thread ever
        looked at this run."""
        from etsy_listings.ui.runs.events import PhaseEvent

        self.events.append(PhaseEvent(id=self._next_event_id, phase=self.phase))
        self._next_event_id += 1

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

    def transition(self, phase: RunPhase) -> None:
        """Move to ``phase``, recording it as a :class:`~etsy_listings.ui.runs.events.PhaseEvent`
        in the same stroke -- a phase change with no event a client could see
        it happen through would be invisible to anyone already streaming."""
        from etsy_listings.ui.runs.events import PhaseEvent

        with self.condition:
            event = PhaseEvent(id=self._next_event_id, phase=phase)
            self._next_event_id += 1
            self.events.append(event)
            self.phase = phase
            self.condition.notify_all()

    def mark_seen(self) -> None:
        with self.condition:
            self.seen = True

    def wait_for_events(self, after_id: int, *, timeout: float) -> tuple[list[AnyRunEvent], bool]:
        """Block up to ``timeout`` seconds for an event past ``after_id``.

        Returns ``(pending, done)``. ``done`` is true only once the run has
        reached a terminal phase *and* every event up to that phase has
        already been returned -- so a caller that loops on this until ``done``
        is guaranteed to see every event exactly once, in order, with nothing
        dropped between one call and the next (``api/runs.py``'s SSE loop is
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


@dataclass(frozen=True)
class Conflict:
    """``create`` refused: ``active_run`` is already holding one of the
    requested listings, and the caller should reattach to it instead."""

    active_run: str


@dataclass
class RunRegistry:
    """Every run this server process has seen and its current scope holder.

    Listing-scoped runs use ``_holder``. Workspace runs use the separate
    ``_workspace_holder`` because a terminal workspace plan remains the
    current review until its linked apply replaces it (A34).
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _runs: dict[str, Run] = field(default_factory=dict)
    _holder: dict[str, str] = field(default_factory=dict)
    _workspace_holder: str | None = None
    _queue: queue.Queue[str] = field(default_factory=queue.Queue)
    _id_source: Callable[[], str] = field(default=lambda: uuid.uuid4().hex)

    def create(
        self,
        kind: RunKind,
        listings: Sequence[str],
        *,
        expect: Mapping[str, str] | None = None,
        scope: RunScope = "listings",
        reviewed_run_id: str | None = None,
    ) -> Run | Conflict:
        """A new run for ``listings``, queued for the executor -- or the
        holder already busy with one of them, unmodified, for the caller to
        report as a ``409`` naming a run to reattach to instead."""
        with self._lock:
            if scope == "workspace":
                workspace_holder = self._runs.get(self._workspace_holder or "")
                if workspace_holder is not None and workspace_holder.phase not in TERMINAL_PHASES:
                    return Conflict(active_run=workspace_holder.id)
                for holder_id in self._holder.values():
                    holder = self._runs.get(holder_id)
                    if holder is not None and holder.phase not in TERMINAL_PHASES:
                        return Conflict(active_run=holder.id)
            else:
                workspace_holder = self._runs.get(self._workspace_holder or "")
                if workspace_holder is not None and workspace_holder.phase not in TERMINAL_PHASES:
                    return Conflict(active_run=workspace_holder.id)
                for name in listings:
                    holder = self._runs.get(self._holder.get(name, ""))
                    if holder is not None and holder.phase not in TERMINAL_PHASES:
                        return Conflict(active_run=holder.id)
            run = Run(
                id=self._id_source(),
                kind=kind,
                listings=tuple(listings),
                expect=expect,
                scope=scope,
                reviewed_run_id=reviewed_run_id,
            )
            self._runs[run.id] = run
            if scope == "workspace":
                self._workspace_holder = run.id
            else:
                for name in listings:
                    self._holder[name] = run.id
            self._queue.put(run.id)
            return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def has_active_run(self) -> bool:
        """Whether any run this process knows about is still in a
        non-terminal phase -- what ``ui/desktop.py``'s close handler checks
        before deciding whether shutdown is instant or worth a message
        (decision 7)."""
        with self._lock:
            return any(run.phase not in TERMINAL_PHASES for run in self._runs.values())

    def all_runs(self) -> list[Run]:
        """Every run this process still remembers, for ``GET /api/runs`` with
        no ``listing`` filter -- a workspace-wide view a future batch runner
        or dashboard can use; today's editor always filters by listing."""
        with self._lock:
            return list(self._runs.values())

    def for_listing(self, name: str) -> list[Run]:
        """The current run holding ``name``, active or finished -- a list of
        at most one, in the shape the endpoint contract promises (decision
        7): this registry keeps exactly one holder per listing, superseded
        wholesale by the next ``create`` for it, never several to merge."""
        with self._lock:
            run = self._runs.get(self._holder.get(name, ""))
            return [run] if run is not None else []

    def for_workspace(self) -> list[Run]:
        """The latest workspace-scoped run, including a finished plan that
        remains the review source until a later workspace run replaces it."""
        with self._lock:
            run = self._runs.get(self._workspace_holder or "")
            return [run] if run is not None else []

    def for_scope(self, scope: RunScope) -> list[Run]:
        """Every retained run of one scope, for an explicit scope query."""
        with self._lock:
            return [run for run in self._runs.values() if run.scope == scope]

    def dequeue(self, *, timeout: float) -> str | None:
        """The next queued run id, for the executor's worker thread. ``None``
        on a timeout, which is what lets that thread notice a stop flag
        without blocking on this forever."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain_and_cancel(self) -> None:
        """Every run still sitting in the queue, marked ``cancelled`` without
        ever running -- shutdown's "a queued run is cancelled" (decision 7).
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
            if run is not None and run.phase not in TERMINAL_PHASES:
                run.transition("cancelled")

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
        run.cancel_requested = True
        if run.phase == "queued":
            run.transition("cancelled")
        return True

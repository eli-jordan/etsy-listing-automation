"""The pause a backup puts on the server's background jobs (workspace-backup
spec, *Pausing jobs*; plan decision P4).

One gate per server, shared by every coordinator the lifespan starts: the
deploy executor, the AI coordinator and its batch queue, Prepare and the
scene warmer. It lives in ``core/application`` because Import Linter keeps
core free of server imports and every coordinator here checks it.

**Admission, not a flag.** A unit of work is admitted at the moment it
starts and holds its :class:`Ticket` until it ends. Checking ``paused`` and
then starting would leave a window in which a backup's
:meth:`JobGate.wait_idle` sees nothing in flight while a job is about to
begin; taking the ticket under the gate's own lock closes it. So
:meth:`~JobGate.wait_idle` counts tickets, and work the pause holds back is
never counted -- it has not started, and counting it would wait for itself.

**Three ways in**, one per kind of caller:

- :meth:`~JobGate.admit` -- now or not at all. For a coordinator whose own
  durable queue is the record of what waits (batch rows, Prepare's
  journal): it leaves the work queued and looks again from
  :meth:`~JobGate.on_resume`.
- :meth:`~JobGate.hold` -- start now, or in line once the pause ends. For
  work with nowhere else to wait (a manual AI run). The gate keeps the line,
  so a resume landing just before the work joins it still starts it.
- :meth:`~JobGate.wait_admit` -- block in line until admitted. For a worker
  thread's loop (the deploy executor, the scene warmer).

What a ticket is handed to owns it: a run releases it when it finishes, a
``with`` block when it ends. A ``start`` that raises loses its ticket here.

**Pause, then wait.** A backup calls :meth:`~JobGate.pause` first, so
nothing new starts, then :meth:`~JobGate.wait_idle` for what is already
running. Work in flight needs no admission to finish, so a deploy already
waiting in ``yield_to_deploy`` for an AI run to stop still completes.

**Stop overrides.** At shutdown :meth:`~JobGate.stop` closes admission for
good, ends a pending :meth:`~JobGate.wait_idle` and every
:meth:`~JobGate.wait_admit`, and starts nothing in line. It comes before
each coordinator's own stop (the server lifespan's order), which drops what
it holds as it drops queued work; a worker blocked in ``wait_admit`` is
released only by it.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class Ticket:
    """One admitted unit of work, counted by :meth:`JobGate.wait_idle` until
    released. Releasing twice is harmless; a ``with`` block releases it."""

    def __init__(self, job: str, release: Callable[[], None]) -> None:
        self._release = release
        self.job = job
        """What the backup status names while it waits for this."""

    def release(self) -> None:
        self._release()

    def __enter__(self) -> Ticket:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


@dataclass(eq=False)
class _Place:
    """A place in line: ``start`` to call once admitted, or, for a blocked
    :meth:`JobGate.wait_admit`, the ticket it is handed."""

    job: str
    start: Callable[[Ticket], object] | None
    ticket: Ticket | None = None


class JobGate:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._paused = False
        self._stopped = False
        self._in_flight: dict[int, str] = {}
        """Admitted work by admission number, oldest first."""
        self._numbers = itertools.count()
        self._line: deque[_Place] = deque()
        """Work held for the pause to end, in the order it asked."""
        self._admitting = threading.RLock()
        """One thread at a time starts the line, so it starts in order."""
        self._listeners: list[Callable[[], None]] = []

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    @property
    def waiting_for(self) -> str | None:
        """The oldest work still in flight, or ``None``."""
        with self._condition:
            return next(iter(self._in_flight.values()), None)

    def holds(self, *, queued: bool) -> bool:
        """Whether work that is ``queued`` -- asked for, not started -- is
        held by a backup's pause: what ``waiting_for_backup`` reports. Never
        stored; work queued with no pause on is only waiting its turn."""
        return queued and self.paused

    # ------------------------------------------------------------ the work

    def on_resume(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` after each :meth:`resume`, so a coordinator
        looks again at the queue it keeps. Called outside the gate's lock,
        after the line has started; one that raises is logged and the rest
        still hear."""
        with self._condition:
            self._listeners.append(listener)

    def admit(self, job: str) -> Ticket | None:
        """A ticket for work named ``job`` starting now, or ``None`` while
        paused: the caller leaves the work queued and looks again on
        resume."""
        with self._condition:
            if self._paused or self._line:
                return None
            return self._ticket(job)

    def hold(self, job: str, start: Callable[[Ticket], object]) -> None:
        """Call ``start`` with a ticket for ``job`` now, or -- while paused
        -- once the pause ends, after the work that joined the line before
        it. ``start`` owns the ticket; if it raises, the ticket is released
        and the error logged. Never called after :meth:`stop`."""
        with self._condition:
            if self._stopped:
                return
            self._line.append(_Place(job, start))
        self._start_line()

    def wait_admit(self, job: str) -> Ticket | None:
        """Block in line until ``job`` is admitted, and answer its ticket;
        ``None`` once :meth:`stop` has closed admission."""
        place = _Place(job, None)
        with self._condition:
            if self._stopped:
                return None
            self._line.append(place)
        self._start_line()
        with self._condition:
            self._condition.wait_for(lambda: place.ticket is not None or self._stopped)
            if place.ticket is None:
                self._line.remove(place)
            return place.ticket

    # ---------------------------------------------------------- the backup

    def pause(self) -> None:
        """Admit nothing until :meth:`resume`."""
        with self._condition:
            self._paused = True
            self._condition.notify_all()

    def resume(self) -> None:
        """Admit again: start the line in order, then tell every
        coordinator in the order they asked. Does nothing after
        :meth:`stop`."""
        with self._condition:
            if self._stopped:
                return
            self._paused = False
            listeners = list(self._listeners)
            self._condition.notify_all()
        self._start_line()
        for listener in listeners:
            try:
                listener()
            except Exception:
                logger.exception("a background coordinator could not resume")

    def stop(self) -> None:
        """Shutdown: admit nothing ever again, end a pending
        :meth:`wait_idle` and every :meth:`wait_admit`, and start nothing in
        line."""
        with self._condition:
            self._stopped = True
            self._paused = True
            self._condition.notify_all()

    def wait_idle(self, *, waiting: Callable[[str], None] | None = None) -> bool:
        """Block until no admitted work is in flight, with no timeout (spec,
        *Pausing jobs*). ``waiting`` hears the job waited for each time it
        changes, so status can name it. ``False`` when :meth:`stop` ended
        the wait."""
        named: str | None = None
        with self._condition:
            while self._in_flight and not self._stopped:
                job = next(iter(self._in_flight.values()))
                if job != named and waiting is not None:
                    waiting(job)
                named = job
                self._condition.wait()
            return not self._stopped

    # ------------------------------------------------------------- inside

    def _start_line(self) -> None:
        """Admit the line in order while the gate is open. A pause landing
        part way holds the rest; one ``start`` failing starts the next."""
        with self._admitting:
            while True:
                with self._condition:
                    if self._paused or not self._line:
                        return
                    place = self._line.popleft()
                    ticket = self._ticket(place.job)
                    if place.start is None:
                        place.ticket = ticket
                        self._condition.notify_all()
                        continue
                try:
                    place.start(ticket)
                except Exception:
                    ticket.release()
                    logger.exception("held work for %r could not start", place.job)

    def _ticket(self, job: str) -> Ticket:
        """Under the lock: count ``job`` in flight."""
        number = next(self._numbers)
        self._in_flight[number] = job
        return Ticket(job, lambda: self._release(number))

    def _release(self, number: int) -> None:
        with self._condition:
            if self._in_flight.pop(number, None) is not None:
                self._condition.notify_all()

"""The pause a backup puts on the server's background jobs (workspace-backup
spec, *Pausing jobs*; plan decision P4).

One gate per server, shared by every coordinator the lifespan starts: the
deploy executor, the AI coordinator and its batch queue, Prepare and the
scene warmer. It lives in ``core/application`` because Import Linter keeps
core free of server imports and every coordinator here checks it.

**Admission, not a flag.** A coordinator asks :meth:`JobGate.admit` at the
moment a unit of work starts, and holds the :class:`Ticket` until the work
ends. Checking ``paused`` and then starting would leave a window in which a
backup's :meth:`JobGate.wait_idle` sees nothing in flight while a job is
about to begin; taking the ticket under the gate's own lock closes it. So
:meth:`wait_idle` counts tickets, not each coordinator's own state, and
work a coordinator holds back while paused is never counted -- it has not
started, and counting it would wait for itself.

**Pause, then wait.** A backup calls :meth:`pause` first, so nothing new
starts, then :meth:`wait_idle` for what is already running. Work in flight
needs no admission to finish, so a deploy already waiting in
``yield_to_deploy`` for an AI run to stop still completes.

**Stop overrides.** At shutdown :meth:`stop` ends a pending
:meth:`wait_idle` with ``False`` and leaves the gate paused, so nothing a
coordinator holds is released on the way out; each coordinator's own stop
drops it, as it drops queued work.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable


class Ticket:
    """One admitted unit of work, counted by :meth:`JobGate.wait_idle` until
    released. Releasing twice is harmless."""

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


class JobGate:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._paused = False
        self._stopped = False
        self._in_flight: dict[int, str] = {}
        """Admitted work by admission number, oldest first."""
        self._numbers = itertools.count()
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

    def on_resume(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` after each :meth:`resume`, so a coordinator
        looks at what it held. Called outside the gate's lock."""
        with self._condition:
            self._listeners.append(listener)

    def admit(self, job: str) -> Ticket | None:
        """A ticket for work named ``job`` starting now, or ``None`` while
        paused: the caller holds the work and starts it after a resume."""
        with self._condition:
            if self._paused:
                return None
            number = next(self._numbers)
            self._in_flight[number] = job
            return Ticket(job, lambda: self._release(number))

    def pause(self) -> None:
        """Admit nothing until :meth:`resume`."""
        with self._condition:
            self._paused = True
            self._condition.notify_all()

    def resume(self) -> None:
        """Admit again, and tell every coordinator in the order they asked.
        Does nothing after :meth:`stop`."""
        with self._condition:
            if self._stopped:
                return
            self._paused = False
            listeners = list(self._listeners)
            self._condition.notify_all()
        for listener in listeners:
            listener()

    def stop(self) -> None:
        """Shutdown: end a pending :meth:`wait_idle` and keep held work held."""
        with self._condition:
            self._stopped = True
            self._condition.notify_all()

    def wait_open(self, *, timeout: float) -> bool:
        """Block up to ``timeout`` seconds while paused; whether it is open."""
        with self._condition:
            return self._condition.wait_for(lambda: not self._paused, timeout=timeout)

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

    def _release(self, number: int) -> None:
        with self._condition:
            if self._in_flight.pop(number, None) is not None:
                self._condition.notify_all()

"""Bounded entry/release gates for tests whose operations compete (T03, T08).

A test that needs two operations to overlap must not guess at the scheduler:
no fixed sleeps between starts, no slowing every YAML dump or path move.
Instead the intended first operation announces that it has *entered* the
owned dependency (a lock, a run's context) and waits there on a *release*,
and the test starts its contender only once that entry is seen.

Every wait is bounded and fails with a message naming what never happened,
so a broken ordering is a clear failure rather than a hung suite. Helper
threads are started through :func:`workers`, which releases every gate and
joins every thread in ``finally``: nothing outlives a failing test.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import pytest

GATE_TIMEOUT = 15.0
"""Long enough for a loaded runner; reached only when something is broken."""

STAYS_OUT = 0.2
"""How long a contender is given to (wrongly) get past a held lock. Correct
code can never fail this check, so it cannot cause a false failure; it only
bounds how quickly a broken lock is caught."""


class Gate:
    """One entry/release pair. The gated code calls :meth:`hold`; the test
    calls :meth:`wait_entered`, does what must happen during the hold, then
    :meth:`release`."""

    def __init__(self, what: str, *, timeout: float = GATE_TIMEOUT) -> None:
        self.what = what
        self.timeout = timeout
        self._entered = threading.Event()
        self._released = threading.Event()

    @property
    def entered(self) -> bool:
        return self._entered.is_set()

    def hold(self) -> None:
        self._entered.set()
        if not self._released.wait(self.timeout):
            raise AssertionError(f"{self.what} was held {self.timeout}s and never released")

    def wait_entered(self) -> None:
        if not self._entered.wait(self.timeout):
            pytest.fail(f"{self.what} never reached its gate within {self.timeout}s")

    def release(self) -> None:
        self._released.set()


class LockGate:
    """Wraps a lock-taking context manager so the first operation to take it
    once armed (the holder) holds its gate *inside* the lock, and the next
    operation from another thread (the contender) is observed asking for the
    lock and entering it.

    Only a thread's outermost acquisition counts: an operation that re-enters
    its own lock, or takes it again for a second name, is one operation.
    """

    def __init__(self, what: str) -> None:
        self.held = Gate(f"{what}'s lock holder")
        self._what = what
        self._guard = threading.Lock()
        self._holder: int | None = None
        self._contender: int | None = None
        self._asked = threading.Event()
        self._entered = threading.Event()
        self._depth = threading.local()

    @contextmanager
    def around(self, acquire: Callable[[], AbstractContextManager[Any]]) -> Iterator[None]:
        me = threading.get_ident()
        depth: int = getattr(self._depth, "n", 0)
        role = self._role(me) if depth == 0 else None
        if role == "contender":
            self._asked.set()
        self._depth.n = depth + 1
        try:
            with acquire():
                if role == "holder":
                    self.held.hold()
                elif role == "contender":
                    self._entered.set()
                yield
        finally:
            self._depth.n = depth

    def _role(self, me: int) -> str | None:
        with self._guard:
            if self._holder is None:
                self._holder = me
                return "holder"
            if me == self._holder or self._contender not in (None, me):
                return None
            if self._contender is None:
                self._contender = me
                return "contender"
            return None

    def assert_contender_kept_out(self) -> None:
        """The contender asked for the lock and did not get it while the
        holder held it."""
        if not self._asked.wait(self.held.timeout):
            pytest.fail(f"no contender ever asked for {self._what}'s lock")
        assert not self._entered.wait(STAYS_OUT), (
            f"a contender entered {self._what}'s lock while its holder held it"
        )


class Worker:
    """A named helper thread that keeps its call's return value or raised
    exception for the test."""

    def __init__(self, name: str, call: Callable[[], object]) -> None:
        self._call = call
        self._value: object = None
        self._error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        try:
            self._value = self._call()
        except BaseException as exc:  # handed back to the test thread
            self._error = exc

    def join(self, timeout: float = GATE_TIMEOUT) -> None:
        self.thread.join(timeout)
        if self.thread.is_alive():
            pytest.fail(f"{self.thread.name} did not finish within {timeout}s")

    def outcome(self) -> object:
        """The call's value, or the exception it raised in its place."""
        self.join()
        return self._error if self._error is not None else self._value

    def result(self) -> object:
        """The call's value; the exception it raised is re-raised here."""
        self.join()
        if self._error is not None:
            raise self._error
        return self._value


@contextmanager
def workers(*gates: Gate | LockGate) -> Iterator[Callable[[str, Callable[[], object]], Worker]]:
    """Yields ``start(name, call)``. On the way out, pass or fail, every gate
    is released and every started worker joined."""
    started: list[Worker] = []

    def start(name: str, call: Callable[[], object]) -> Worker:
        worker = Worker(name, call)
        started.append(worker)
        worker.thread.start()
        return worker

    try:
        yield start
    finally:
        for gate in gates:
            (gate.held if isinstance(gate, LockGate) else gate).release()
        for worker in started:
            worker.thread.join(GATE_TIMEOUT)
        alive = [w.thread.name for w in started if w.thread.is_alive()]
        assert not alive, f"helper threads outlived the test: {alive}"

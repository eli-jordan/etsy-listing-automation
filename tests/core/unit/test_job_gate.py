"""``core/application/job_gate.py``: the pause a backup puts on the server's
background jobs (workspace-backup spec, *Pausing jobs*).

The gate on its own, driven from threads as a backup and the coordinators
drive it. The races every coordinator shares -- a resume before work joins
the line, a pause part way through starting it, work failing after its
admission, shutdown -- are tested here once. What each coordinator holds is
that coordinator's behaviour test.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from etsy_listings.core.application.job_gate import JobGate, Ticket

WAIT = 5.0


def _in_thread(gate: JobGate, waited: list[str]) -> tuple[threading.Thread, list[bool]]:
    """A backup's wait for quiet, on its own thread."""
    result: list[bool] = []
    thread = threading.Thread(
        target=lambda: result.append(gate.wait_idle(waiting=waited.append)), daemon=True
    )
    thread.start()
    return thread, result


def _admitted_in_thread(gate: JobGate, job: str) -> tuple[threading.Thread, list[Ticket | None]]:
    """A worker's loop blocked in :meth:`JobGate.wait_admit`."""
    result: list[Ticket | None] = []
    thread = threading.Thread(target=lambda: result.append(gate.wait_admit(job)), daemon=True)
    thread.start()
    return thread, result


def _keeping(started: list[str], tickets: list[Ticket], name: str) -> Callable[[Ticket], None]:
    def start(ticket: Ticket) -> None:
        started.append(name)
        tickets.append(ticket)

    return start


def _idle(gate: JobGate) -> bool:
    """Whether a backup's wait for quiet would return at once."""
    return gate.waiting_for is None


# ------------------------------------------------------------ admission


def test_work_is_admitted_until_a_pause_and_again_after_resume() -> None:
    gate = JobGate()

    assert gate.admit("plan of take-a-hike") is not None
    gate.pause()
    assert gate.paused
    assert gate.admit("plan of take-a-hike") is None
    gate.resume()
    assert not gate.paused
    assert gate.admit("plan of take-a-hike") is not None


def test_only_queued_work_during_a_pause_is_held_by_the_backup() -> None:
    gate = JobGate()
    assert not gate.holds(queued=True), "queued with no pause is only waiting its turn"
    gate.pause()

    assert gate.holds(queued=True)
    assert not gate.holds(queued=False)


def test_a_ticket_is_released_once_however_often_it_is_released() -> None:
    gate = JobGate()
    first = gate.admit("AI run for take-a-hike")
    second = gate.admit("AI run for cedar-trail")
    assert first is not None
    assert second is not None

    with first:
        pass
    first.release()

    assert gate.waiting_for == "AI run for cedar-trail"


# ------------------------------------------------------------- the line


def test_held_work_starts_at_once_while_open() -> None:
    gate = JobGate()
    started: list[str] = []
    tickets: list[Ticket] = []

    gate.hold("AI run for take-a-hike", _keeping(started, tickets, "take-a-hike"))

    assert started == ["take-a-hike"]
    assert gate.waiting_for == "AI run for take-a-hike"
    tickets[0].release()
    assert _idle(gate)


def test_held_work_is_not_counted_and_starts_on_resume_in_order_before_listeners() -> None:
    gate = JobGate()
    started: list[str] = []
    tickets: list[Ticket] = []
    gate.on_resume(lambda: started.append("listener"))
    gate.pause()

    gate.hold("AI run for take-a-hike", _keeping(started, tickets, "take-a-hike"))
    gate.hold("AI run for cedar-trail", _keeping(started, tickets, "cedar-trail"))
    assert started == []
    assert gate.wait_idle() is True, "held work has not started, so nothing is in flight"

    gate.resume()

    assert started == ["take-a-hike", "cedar-trail", "listener"]
    assert gate.waiting_for == "AI run for take-a-hike"


def test_work_held_just_after_a_resume_still_starts() -> None:
    """The race a manual run had: the pause ends between its admission
    being refused and it joining the line."""
    gate = JobGate()
    gate.pause()
    assert gate.admit("AI run for take-a-hike") is None
    gate.resume()
    started: list[str] = []

    gate.hold("AI run for take-a-hike", _keeping(started, [], "take-a-hike"))

    assert started == ["take-a-hike"]


def test_a_pause_landing_part_way_through_the_line_holds_the_rest() -> None:
    gate = JobGate()
    started: list[str] = []
    tickets: list[Ticket] = []

    def first(ticket: Ticket) -> None:
        _keeping(started, tickets, "first")(ticket)
        gate.pause()

    gate.pause()
    gate.hold("first", first)
    gate.hold("second", _keeping(started, tickets, "second"))

    gate.resume()
    assert started == ["first"]
    tickets[0].release()
    gate.resume()

    assert started == ["first", "second"]


def test_new_work_waits_behind_the_line_while_it_starts() -> None:
    """Admitted-now work does not jump ahead of held work the resume has
    not started yet."""
    gate = JobGate()
    admitted: list[Ticket | None] = []
    gate.pause()
    gate.hold("first", lambda _ticket: admitted.append(gate.admit("newcomer")))
    gate.hold("second", lambda _ticket: None)

    gate.resume()

    assert admitted == [None]
    assert gate.admit("newcomer") is not None


def test_work_that_fails_after_admission_releases_its_ticket_and_the_line_goes_on() -> None:
    """A journal write failing after the ticket was taken leaves the backup
    nothing to wait for."""
    gate = JobGate()
    started: list[str] = []

    def failing(_ticket: Ticket) -> None:
        raise OSError("the batch row could not be saved")

    gate.pause()
    gate.hold("failing", failing)
    gate.hold("next", _keeping(started, [], "next"))

    gate.resume()

    assert started == ["next"]
    assert gate.waiting_for == "next"


def test_a_failing_resume_listener_leaves_the_others_to_resume() -> None:
    gate = JobGate()
    heard: list[str] = []

    def failing() -> None:
        raise RuntimeError("prepare could not schedule")

    gate.on_resume(lambda: heard.append("deploy"))
    gate.on_resume(failing)
    gate.on_resume(lambda: heard.append("ai"))
    gate.pause()

    gate.resume()

    assert heard == ["deploy", "ai"]


# --------------------------------------------------------- worker loops


def test_a_worker_waits_in_line_until_resume_and_then_holds_a_ticket() -> None:
    gate = JobGate()
    gate.pause()
    started: list[str] = []
    gate.hold("held first", _keeping(started, [], "held first"))

    thread, result = _admitted_in_thread(gate, "Deploy plan for take-a-hike")
    thread.join(0.2)
    assert thread.is_alive(), "the worker was admitted while paused"
    gate.resume()
    thread.join(WAIT)

    ticket = result[0]
    assert ticket is not None
    assert started == ["held first"], "the worker joined the line after the held work"
    assert ticket.job == "Deploy plan for take-a-hike"


def test_an_open_gate_admits_a_worker_at_once() -> None:
    gate = JobGate()

    ticket = gate.wait_admit("Scene warming for take-a-hike")

    assert ticket is not None
    assert gate.waiting_for == "Scene warming for take-a-hike"


# ------------------------------------------------------- waiting for quiet


def test_wait_idle_returns_at_once_when_nothing_is_in_flight() -> None:
    gate = JobGate()
    gate.pause()

    assert gate.wait_idle() is True


def test_wait_idle_names_each_job_it_waits_for_and_returns_when_the_last_ends() -> None:
    gate = JobGate()
    deploy = gate.admit("Plan of take-a-hike")
    warming = gate.admit("Scene warming")
    assert deploy is not None
    assert warming is not None
    gate.pause()
    waited: list[str] = []

    thread, result = _in_thread(gate, waited)
    deploy.release()
    thread.join(0.2)
    assert thread.is_alive(), "wait_idle returned with a warming pass still in flight"
    warming.release()
    thread.join(WAIT)

    assert result == [True]
    assert waited == ["Plan of take-a-hike", "Scene warming"]


# ---------------------------------------------------------------- shutdown


def test_stop_ends_a_wait_and_a_later_resume_starts_nothing_held() -> None:
    gate = JobGate()
    ticket = gate.admit("Prepare job for flat-lay-01")
    assert ticket is not None
    heard: list[str] = []
    gate.on_resume(lambda: heard.append("resumed"))
    gate.pause()
    gate.hold("AI run for take-a-hike", lambda _ticket: heard.append("started"))

    thread, result = _in_thread(gate, [])
    gate.stop()
    thread.join(WAIT)
    gate.resume()

    assert result == [False]
    assert gate.paused, "shutdown during a pause must not release held work"
    assert heard == []


def test_stop_lets_a_waiting_worker_go_without_a_ticket() -> None:
    gate = JobGate()
    gate.pause()
    thread, result = _admitted_in_thread(gate, "Workspace apply")
    thread.join(0.2)
    assert thread.is_alive()

    gate.stop()
    thread.join(WAIT)

    assert result == [None]


@pytest.mark.parametrize("paused", [False, True])
def test_a_stopped_gate_admits_nothing_by_any_way_in(*, paused: bool) -> None:
    gate = JobGate()
    if paused:
        gate.pause()
    started: list[str] = []

    gate.stop()
    gate.hold("Deploy", _keeping(started, [], "held"))

    assert gate.admit("Deploy") is None
    assert gate.wait_admit("Deploy") is None
    assert started == []

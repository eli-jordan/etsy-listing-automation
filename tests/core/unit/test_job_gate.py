"""``core/application/job_gate.py``: the pause a backup puts on the server's
background jobs (workspace-backup spec, *Pausing jobs*).

The gate on its own, driven from threads as a backup and the coordinators
drive it. What each coordinator does with it is that coordinator's
behaviour test.
"""

from __future__ import annotations

import threading

from etsy_listings.core.application.job_gate import JobGate

WAIT = 5.0


def _in_thread(gate: JobGate, waited: list[str]) -> tuple[threading.Thread, list[bool]]:
    result: list[bool] = []
    thread = threading.Thread(
        target=lambda: result.append(gate.wait_idle(waiting=waited.append)), daemon=True
    )
    thread.start()
    return thread, result


def test_work_is_admitted_until_a_pause_and_again_after_resume() -> None:
    gate = JobGate()

    assert gate.admit("plan of take-a-hike") is not None
    gate.pause()
    assert gate.paused
    assert gate.admit("plan of take-a-hike") is None
    gate.resume()
    assert not gate.paused
    assert gate.admit("plan of take-a-hike") is not None


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


def test_resume_tells_every_coordinator_in_the_order_they_asked() -> None:
    gate = JobGate()
    heard: list[str] = []
    gate.on_resume(lambda: heard.append("deploy"))
    gate.on_resume(lambda: heard.append("ai"))
    gate.pause()

    gate.resume()

    assert heard == ["deploy", "ai"]


def test_wait_open_blocks_only_while_paused() -> None:
    gate = JobGate()
    assert gate.wait_open(timeout=0) is True
    gate.pause()
    assert gate.wait_open(timeout=0.05) is False
    threading.Timer(0.05, gate.resume).start()
    assert gate.wait_open(timeout=WAIT) is True


def test_stop_ends_a_wait_and_a_later_resume_releases_nothing() -> None:
    gate = JobGate()
    ticket = gate.admit("Prepare job for flat-lay-01")
    assert ticket is not None
    heard: list[str] = []
    gate.on_resume(lambda: heard.append("resumed"))
    gate.pause()

    thread, result = _in_thread(gate, [])
    gate.stop()
    thread.join(WAIT)
    gate.resume()

    assert result == [False]
    assert gate.paused, "shutdown during a pause must not release held work"
    assert heard == []


def test_stopping_an_open_gate_blocks_new_work() -> None:
    gate = JobGate()

    gate.stop()

    assert gate.admit("Deploy") is None
    assert not gate.wait_open(timeout=0)

"""Header pacing on the Etsy transport (market-seo.md, *Quota*).

Every Etsy response says how many calls are left this second. When that
reaches 0, the next call waits for the next second rather than spending a
429 and a retry to learn the same thing. Market research runs five calls at
once, so the rule has to hold across threads -- and has to wait by sleeping
once, not by spinning.

Time here is a fake: ``clock`` reads it and ``sleep`` advances it, so every
assertion about *when* is exact and instant.
"""

from __future__ import annotations

import logging
import threading

import httpx
import pytest

from etsy_listings.clients.etsy.transport import BASE_URL, RateGate, Transport
from etsy_listings.config.secrets import EtsyAppKey


class FakeTime:
    def __init__(self, now: float = 100.0) -> None:
        self._now = now
        self._lock = threading.Lock()
        self.slept: list[float] = []

    def clock(self) -> float:
        with self._lock:
            return self._now

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.slept.append(seconds)
            self._now += seconds

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


def _headers(remaining: int | str | None) -> dict[str, str]:
    headers = {
        "x-limit-per-second": "10",
        "x-limit-per-day": "10000",
        "x-remaining-today": "9876",
    }
    if remaining is not None:
        headers["x-remaining-this-second"] = str(remaining)
    return headers


def _transport(time: FakeTime, handler) -> Transport:  # noqa: ANN001 - a test handler
    return Transport(
        EtsyAppKey("k", "s"),
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url=BASE_URL),
        sleep=time.sleep,
        clock=time.clock,
    )


def _answering(time: FakeTime, *remaining: int | str | None):  # noqa: ANN202
    """A handler answering each request with the next header value (the last
    one repeats), recording the fake time every request was *sent* at."""
    queue = list(remaining)
    sent: list[float] = []
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            sent.append(time.clock())
            value = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(200, headers=_headers(value), json={})

    return handler, sent


def test_a_call_after_the_last_one_this_second_waits_for_the_next_second() -> None:
    time = FakeTime()
    handler, sent = _answering(time, 0, 9)
    transport = _transport(time, handler)

    transport.get("/v3/application/listings/active")
    transport.get("/v3/application/listings/active")

    assert time.slept == [1.0]
    assert sent == [100.0, 101.0]


def test_the_wait_is_only_what_is_left_of_the_second() -> None:
    time = FakeTime()
    handler, sent = _answering(time, 0, 9)
    transport = _transport(time, handler)

    transport.get("/a")
    time.advance(0.75)
    transport.get("/b")

    assert time.slept == [pytest.approx(0.25)]
    assert sent == [100.0, 101.0]


def test_a_call_made_after_the_second_has_passed_does_not_wait() -> None:
    time = FakeTime()
    handler, _ = _answering(time, 0, 9)
    transport = _transport(time, handler)

    transport.get("/a")
    time.advance(1.5)
    transport.get("/b")

    assert time.slept == []


@pytest.mark.parametrize("remaining", [9, 1, None, "not-a-number"])
def test_calls_left_this_second_or_no_readable_header_means_no_wait(
    remaining: int | str | None,
) -> None:
    """A missing or garbled header is read as "no information", never as
    "stop": pacing is an optimisation over the 429 retry, not a gate that
    can wedge a run on a proxy that strips headers."""
    time = FakeTime()
    handler, _ = _answering(time, remaining)
    transport = _transport(time, handler)

    transport.get("/a")
    transport.get("/b")

    assert time.slept == []


def test_the_pacing_holds_across_five_threads_with_one_sleep() -> None:
    """Five market calls in flight at once (market-seo.md, *Quota*) share
    one gate: none is sent before the next second, and the wait is a single
    sleep that the others block behind -- not five sleeps, and not a poll."""
    time = FakeTime()
    handler, sent = _answering(time, 0, 9)
    transport = _transport(time, handler)
    transport.get("/first")

    start = threading.Barrier(5)
    errors: list[BaseException] = []

    def call() -> None:
        try:
            start.wait()
            transport.get("/concurrent")
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(sent) == 6
    assert all(at >= 101.0 for at in sent[1:])
    assert time.slept == [1.0]


def test_a_later_response_with_calls_left_does_not_lift_a_wait_already_owed() -> None:
    """Responses from concurrent calls arrive in any order. One that left the
    server before the budget ran out must not cancel the wait another has
    just established."""
    time = FakeTime()
    gate = RateGate(clock=time.clock, sleep=time.sleep)

    gate.observe(httpx.Headers(_headers(0)))
    gate.observe(httpx.Headers(_headers(7)))
    gate.wait()

    assert time.slept == [1.0]


def test_the_daily_budget_is_logged_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    """Logged, never stored: Etsy's limits are per app and set in the
    developer portal, so no budget is kept anywhere (market-seo.md, *Quota*)."""
    time = FakeTime()
    handler, _ = _answering(time, 9)
    transport = _transport(time, handler)

    with caplog.at_level(logging.DEBUG, logger="etsy_listings.clients.etsy.transport"):
        transport.get("/a")

    [record] = [r for r in caplog.records if "remaining today" in r.getMessage()]
    assert record.levelno == logging.DEBUG
    assert "9876" in record.getMessage()
    assert "10000" in record.getMessage()

"""A21: when a failed request is worth sending again, and how long to wait.

The delays are computed here rather than slept, so every test is instant and
deterministic -- the jitter source and the clock are both injected.

The rule that carries the most weight is the one about methods. A 429 means
Printify rejected the request before doing anything with it, so resending is
free whatever the verb. A 500 means nothing of the sort: the write may well
have landed, and `create_product` has no idempotency key and no conflict, so a
retried POST is exactly how one design becomes two products (PRD 48).
"""

from __future__ import annotations

import httpx
import pytest

from etsy_listings.clients.retry import RetryPolicy, should_retry, wait_for, with_retries


def _response(status: int, **headers: str) -> httpx.Response:
    return httpx.Response(status, headers=headers, request=httpx.Request("GET", "https://x/"))


# ------------------------------------------------------- what is worth retrying


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_transient_failure_on_an_idempotent_method_is_retried(status: int) -> None:
    assert should_retry("GET", _response(status)) is True


@pytest.mark.parametrize("status", [200, 201, 400, 401, 403, 404, 422])
def test_a_verdict_is_not_retried(status: int) -> None:
    """4xx is Printify saying the request is wrong. Sending it again produces
    the same answer and burns the rate-limit budget doing it."""
    assert should_retry("GET", _response(status)) is False


def test_a_rejected_post_is_retried_because_nothing_happened() -> None:
    """429 is a refusal to process, not a failure while processing."""
    assert should_retry("POST", _response(429)) is True


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_post_that_may_have_landed_is_never_retried(status: int) -> None:
    """The whole reason this function takes a method. `create_product` is the
    one non-idempotent call in the system, and a 500 does not say whether the
    product was created -- so a retry here is how a crash becomes a duplicate."""
    assert should_retry("POST", _response(status)) is False


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "HEAD"])
def test_every_idempotent_method_may_be_retried_on_a_server_error(method: str) -> None:
    assert should_retry(method, _response(503)) is True


def test_the_method_check_is_case_insensitive() -> None:
    assert should_retry("post", _response(500)) is False


# ------------------------------------------------------------- how long to wait


POLICY = RetryPolicy(attempts=4, base_delay=0.5, max_delay=30.0, jitter=0.0)


def test_the_delay_doubles_with_each_attempt() -> None:
    assert [wait_for(POLICY, attempt, None) for attempt in range(4)] == [0.5, 1.0, 2.0, 4.0]


def test_the_delay_is_capped() -> None:
    policy = RetryPolicy(attempts=20, base_delay=1.0, max_delay=10.0, jitter=0.0)

    assert wait_for(policy, 10, None) == 10.0


def test_jitter_moves_the_delay_within_its_band() -> None:
    """Jitter exists so a batch that hits the limit together does not retry
    together. It is a fraction of the delay, not a fixed spread."""
    policy = RetryPolicy(attempts=4, base_delay=1.0, max_delay=30.0, jitter=0.5)

    assert wait_for(policy, 0, None, random=lambda: 0.0) == 0.5
    assert wait_for(policy, 0, None, random=lambda: 1.0) == 1.5


def test_retry_after_in_seconds_wins_over_the_computed_backoff() -> None:
    """Printify saying when to come back beats us guessing."""
    assert wait_for(POLICY, 0, _response(429, **{"Retry-After": "7"})) == 7.0


def test_retry_after_is_still_capped() -> None:
    """A server asking for an hour is not a reason to block for an hour."""
    assert wait_for(POLICY, 0, _response(429, **{"Retry-After": "3600"})) == 30.0


def test_an_unparseable_retry_after_falls_back_to_the_backoff() -> None:
    """Its other legal form is an HTTP-date, and a proxy can put anything
    there. Neither is a reason to crash on the way to a retry."""
    assert (
        wait_for(POLICY, 1, _response(429, **{"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}))
        == 1.0
    )


def test_a_negative_retry_after_does_not_become_a_negative_sleep() -> None:
    assert wait_for(POLICY, 0, _response(429, **{"Retry-After": "-5"})) == 0.0


# ------------------------------------------------------------------ the loop


def test_a_successful_call_is_made_once() -> None:
    calls: list[int] = []

    def send() -> httpx.Response:
        calls.append(1)
        return _response(200)

    assert with_retries(send, "GET", POLICY, sleep=lambda _: None).status_code == 200
    assert len(calls) == 1


def test_it_stops_as_soon_as_a_call_succeeds() -> None:
    statuses = iter([503, 429, 200])
    slept: list[float] = []

    response = with_retries(lambda: _response(next(statuses)), "GET", POLICY, sleep=slept.append)

    assert response.status_code == 200
    assert len(slept) == 2, "one sleep per retry, none after the success"


def test_it_gives_up_and_returns_the_last_response() -> None:
    """Returned, not raised: the caller's own error decoding is what turns a
    response into a message a human can act on, and it should see the real
    one rather than a retry wrapper's summary."""
    slept: list[float] = []

    response = with_retries(lambda: _response(503), "GET", POLICY, sleep=slept.append)

    assert response.status_code == 503
    assert len(slept) == POLICY.attempts - 1, "no sleep after the final attempt"


def test_a_non_retryable_failure_is_returned_immediately() -> None:
    slept: list[float] = []

    response = with_retries(lambda: _response(400), "POST", POLICY, sleep=slept.append)

    assert response.status_code == 400
    assert slept == []


def test_a_transport_error_is_retried_on_an_idempotent_method() -> None:
    """A dropped connection is the same ambiguity as a 500 and gets the same
    treatment -- retried where the verb makes it safe."""
    attempts: list[int] = []

    def send() -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("connection reset")
        return _response(200)

    assert with_retries(send, "GET", POLICY, sleep=lambda _: None).status_code == 200
    assert len(attempts) == 3


def test_a_transport_error_on_a_post_is_raised_rather_than_retried() -> None:
    """The request may have reached Printify and been acted on. Resending is
    the duplicate-product path again."""
    with pytest.raises(httpx.ConnectError):
        with_retries(
            lambda: (_ for _ in ()).throw(httpx.ConnectError("reset")),
            "POST",
            POLICY,
            sleep=lambda _: None,
        )


def test_a_transport_error_that_never_clears_is_raised() -> None:
    def send() -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    with pytest.raises(httpx.ConnectError):
        with_retries(send, "GET", POLICY, sleep=lambda _: None)

"""Backoff policy for every Etsy and Printify request. ADR-0009.

**The method matters more than the status.** A 429 is a refusal to process --
Printify rejected the request before touching it, so resending is free
whatever the verb. A 5xx or a dropped connection is the opposite: the write
may well have landed, and ``POST products.json`` has no idempotency key and no
conflict, so a retried create is precisely how one design becomes two products
(ADR-0023, and ``TestNothingStopsUsCreatingTheSameProductTwice`` in the e2e
layer). So idempotent methods are retried on both; POST only on 429.
"""

from __future__ import annotations

import random as _random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
"""429 plus the server-side 5xx. Deliberately not 501 or 505, which are
statements about the request rather than about load."""

TOO_MANY_REQUESTS = 429

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"})
"""Safe to send twice by definition. POST is the whole exclusion, and the
reason this function takes a method at all."""


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    """Total attempts, not retries after the first. Four gives roughly
    0.5 + 1 + 2 seconds of waiting before giving up -- long enough to ride out
    a rate-limit window, short enough that a genuinely broken endpoint is
    reported while the user is still watching."""

    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: float = 0.25
    """Fraction of the delay to spread over. Batch runs hit a limit together,
    and without jitter they come back together and hit it again."""


DEFAULT_POLICY = RetryPolicy()


def should_retry(method: str, response: httpx.Response) -> bool:
    if response.status_code not in RETRYABLE_STATUSES:
        return False
    if response.status_code == TOO_MANY_REQUESTS:
        return True
    return method.upper() in IDEMPOTENT_METHODS


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    """``Retry-After`` as a number of seconds, or ``None``.

    Its other legal form is an HTTP-date, and a proxy in between can put
    anything there at all. Neither is worth crashing on while on the way to a
    retry, so anything unparseable simply falls back to the computed backoff.
    """
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


def wait_for(
    policy: RetryPolicy,
    attempt: int,
    response: httpx.Response | None,
    *,
    random: Callable[[], float] = _random.random,
) -> float:
    """Seconds to wait before attempt ``attempt + 1``."""
    asked = _retry_after_seconds(response)
    if asked is not None:
        return min(asked, policy.max_delay)

    # `2.0**attempt`, not `2**attempt`: mypy types `int ** int` as `Any`
    # (it is float for a negative exponent), which quietly makes every value
    # downstream of it untyped.
    delay = min(policy.base_delay * (2.0**attempt), policy.max_delay)
    if not policy.jitter:
        return delay
    spread = delay * policy.jitter
    return delay - spread + (2 * spread * random())


def _send_once(
    send: Callable[[], httpx.Response], method: str
) -> httpx.Response | httpx.TransportError:
    try:
        return send()
    except httpx.TransportError as exc:
        if method.upper() not in IDEMPOTENT_METHODS:
            raise
        return exc


def with_retries(
    send: Callable[[], httpx.Response],
    method: str,
    policy: RetryPolicy = DEFAULT_POLICY,
    *,
    sleep: Callable[[float], None] = time.sleep,
    random: Callable[[], float] = _random.random,
) -> httpx.Response:
    """Call ``send`` until it succeeds, is refused for a reason retrying cannot
    fix, or runs out of attempts.

    The final response is **returned, not raised**. The caller's own error
    decoding is what turns a response into something a human can act on
    (``errors.reason``, in Printify's case), and it should see the real
    response rather than a wrapper's summary of it. A transport error has no
    response to return, so that one does propagate.
    """
    last = _send_once(send, method)
    for attempt in range(1, policy.attempts):
        if isinstance(last, httpx.Response) and not should_retry(method, last):
            return last
        response = last if isinstance(last, httpx.Response) else None
        sleep(wait_for(policy, attempt - 1, response, random=random))
        last = _send_once(send, method)
    if isinstance(last, httpx.TransportError):
        raise last
    return last

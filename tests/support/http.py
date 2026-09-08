"""A Printify transport wired to a mock handler, for the contract layer.

Every contract file was building the same three-line stack -- a
``MockTransport`` inside an ``httpx.Client`` inside the client under test --
and each got the retry stubbing subtly differently. Once both halves of the
client share one :class:`Transport`, so should the way a test stands one up.

``sleep`` is always stubbed. These tests are about decoding a response, and a
5xx on a GET is retryable (A21), so a real sleep spends the policy's full
backoff -- seconds of nothing -- before an assertion that never needed to
wait.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from etsy_listings.clients.printify import BASE_URL, Transport
from etsy_listings.clients.retry import DEFAULT_POLICY, RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]

INSTANT = RetryPolicy(attempts=2, base_delay=0.0, max_delay=0.0, jitter=0.0)
"""Two attempts, no backoff -- for the tests that count attempts rather than
ride one out."""


def transport(
    handler: Handler,
    *,
    token: str | Callable[[], str] = "test-token",
    policy: RetryPolicy = DEFAULT_POLICY,
) -> Transport:
    """A transport that answers from ``handler`` and never sleeps."""
    return Transport(
        token,
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url=BASE_URL),
        policy=policy,
        sleep=lambda _: None,
    )


def always(response: httpx.Response) -> Handler:
    """A handler that answers every request the same way."""
    return lambda _: response

"""Transports wired to a mock handler, for the contract layer.

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

from etsy_listings.clients.etsy.transport import BASE_URL as ETSY_BASE_URL
from etsy_listings.clients.etsy.transport import OAuthClient
from etsy_listings.clients.etsy.transport import Transport as EtsyTransport
from etsy_listings.clients.printify import BASE_URL, Transport
from etsy_listings.clients.retry import DEFAULT_POLICY, RetryPolicy
from etsy_listings.config.secrets import EtsyAppKey

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


def etsy_transport(
    handler: Handler,
    *,
    app_key: EtsyAppKey = EtsyAppKey("test-keystring", "test-secret"),
    bearer: Callable[[], str] | None = lambda: "12345678.test-access",
    policy: RetryPolicy = DEFAULT_POLICY,
) -> EtsyTransport:
    """The same stack for Etsy. ``bearer=None`` is the unauthenticated case --
    a ping, which is the one call `auth` makes before a token exists."""
    return EtsyTransport(
        app_key,
        bearer=bearer,
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url=ETSY_BASE_URL),
        policy=policy,
        sleep=lambda _: None,
    )


def etsy_oauth_client(
    handler: Handler,
    *,
    keystring: str = "test-keystring",
    policy: RetryPolicy = DEFAULT_POLICY,
) -> OAuthClient:
    """The token endpoint, which carries no credentials of its own -- no base
    URL either, since it is the one absolute URL in the client."""
    return OAuthClient(
        keystring,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        policy=policy,
        sleep=lambda _: None,
    )

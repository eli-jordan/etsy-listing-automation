"""One authenticated connection to ``api.printify.com``, shared by both halves
of the client.

The catalog reader and the shop-scoped writer address different path families
and carry different authority, but they talk to the *same host with the same
token* -- so everything between "here is a path" and "here is a decoded
response" is one thing, and used to be two. The duplicated half was: a
``TokenSource`` alias, a lazy token resolve, a ``401/403`` branch into a
bespoke auth error, a base URL, a timeout, and an ``httpx.Client`` fallback.

Keeping them apart was not free. The catalog reader called
``raise_for_status()`` and had **no retries at all**, so a 429 on
``GET /v1/catalog/blueprints.json`` failed a ``new`` run outright while the
identical 429 on a product write rode out its backoff window (A21). Nobody
decided that; it is what two implementations of one concern drift into.

What stays split is the *authority*: :class:`~...protocol.CatalogClient` and
:class:`~...protocol.PrintifyClient` remain separate protocols over separate
path families, so nothing holding a catalog client can reach a call that
creates a product. That was always the real content of the split, and it lives
in the protocols rather than in a second copy of the plumbing.

Error decoding leans on a shape this API keeps to without exception -- every
failure observed against the live API is

    {"status": "error", "code": 8251, "message": "Validation failed.",
     "errors": {"reason": "...", "code": 8251}}

``errors.reason`` is a human sentence naming the offending field, and is the
only part of that envelope worth putting in front of a user
(docs/api-findings.md).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from etsy_listings.clients.retry import DEFAULT_POLICY, RetryPolicy, with_retries
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.errors import UserFacingError

BASE_URL = "https://api.printify.com"
"""No ``/v1`` suffix: this transport carries several path families
(``/v1/catalog``, ``/v1/shops``, ``/v1/uploads``), and spelling the version
once per path keeps each call site readable as the documented endpoint it is."""

TokenSource = str | Callable[[], str]
"""A token, or something that produces one on demand.

Resolved lazily, never at construction: ``plan`` builds both clients eagerly
and may call neither, a cached catalog read needs no token at all, and
demanding a credential to *build* a client would fail every workspace that has
not yet reached the phase which needs one."""

HTTP_NOT_FOUND = 404

WRONG_SHOP_CODE = 8104
"""Printify's answer for "that product id is real, but it is not in this shop".

A `400`, not the `404` the same question gets when the id is unknown to every
shop -- so "is this product gone?" has two right answers and only one obvious
one. It is reachable in ordinary use: reconnecting a store replaces the shop
id, and a lockfile written against the old one then names a product this shop
has never held. Measured, against a workspace whose Printify store had been
swapped for a natively-connected Etsy one.
"""

DEFAULT_TIMEOUT_SECONDS = 120.0
"""Generous, because uploads travel this transport: a print file is megabytes,
and the default 5s timeout turns a slow link into an inscrutable failure."""


class PrintifyAuthError(UserFacingError, RuntimeError):
    """Printify rejected the credentials. Distinct from every other failure,
    because the fix is a specific human action rather than a retry.

    A specific human action is exactly what a
    :class:`~etsy_listings.errors.UserFacingError` is for, and the message
    below has always been written as one. Until it *was* one, a revoked token
    on the third listing of ``--all`` ended the batch with a stack trace
    instead of a line, against PRD 16.

    One error for both halves. They were two, with two messages naming two
    scopes -- and a user whose token was missing ``catalog.read`` got the
    catalog's advice while a user missing the product scopes got the writer's,
    with no way for either to learn that the other scope exists. The token is
    one token; the message names everything it needs.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Printify rejected the request ({status_code}).\n"
            f"  Check {PRINTIFY_TOKEN_VAR} in your workspace's .env -- if the token is "
            f"present, it is expired, revoked, or missing a scope.\n"
            f"  Reading the catalog needs `catalog.read`; writing products needs the "
            f"shop and product scopes as well.\n"
            f"  Regenerate it at printify.com/app/account/api (docs/setup.md "
            f"section 1.3), or re-run `etsy-listings setup`, which verifies a token "
            f"before storing it."
        )


class PrintifyApiError(UserFacingError, RuntimeError):
    """A request Printify understood and refused.

    User-facing for the same reason as :class:`PrintifyAuthError`: a refusal
    the API explained is a refusal the user can read. A 500 is not actionable
    in the same way, but it is still one listing's failure and not the run's
    -- ending the batch on it loses the forty-nine that would have succeeded.

    Carries ``code`` because Printify's numeric codes are stable enough to
    branch on (8254 is "shop not connected to a sales channel", which
    ``publish`` will want to recognise), and renders ``errors.reason`` because
    that is the part a human can act on.
    """

    def __init__(self, status_code: int, *, code: int | None, reason: str) -> None:
        self.status_code = status_code
        self.code = code
        self.reason = reason
        detail = f" (code {code})" if code is not None else ""
        super().__init__(f"Printify refused the request with {status_code}{detail}: {reason}")


def decode_error(response: httpx.Response) -> PrintifyApiError:
    """Pull ``errors.reason`` out of the envelope, tolerating its absence.

    A 502 from a proxy is HTML, not JSON. Crashing while decoding the thing
    that explains the failure is the worst possible time to crash, so every
    step here degrades rather than raising.
    """
    reason = response.text.strip() or "no response body"
    code: int | None = None
    try:
        body: Any = response.json()
    except ValueError:
        return PrintifyApiError(response.status_code, code=None, reason=reason)

    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, dict) and isinstance(errors.get("reason"), str):
            reason = errors["reason"]
        elif isinstance(body.get("message"), str):
            reason = body["message"]
        if isinstance(body.get("code"), int):
            code = body["code"]
    return PrintifyApiError(response.status_code, code=code, reason=reason)


class Transport:
    """Send a request to Printify and hand back a response worth reading.

    Everything a caller would otherwise repeat: resolving the token, attaching
    it, riding out a retryable failure, and turning a refusal into an error
    that names what to do about it.
    """

    def __init__(
        self,
        token: TokenSource,
        *,
        client: httpx.Client | None = None,
        policy: RetryPolicy = DEFAULT_POLICY,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
        self._policy = policy
        self._sleep = sleep

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self._token if isinstance(self._token, str) else self._token()

        def send() -> httpx.Response:
            return self._client.request(
                method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )

        # Retries happen *before* the error decoding below, so a 429 that
        # clears on the second attempt never becomes an exception at all --
        # and one that does not clear surfaces as the real decoded error
        # rather than a retry wrapper's summary of it (A21).
        response = with_retries(send, method, self._policy, sleep=self._sleep)

        if response.status_code in (401, 403):
            raise PrintifyAuthError(response.status_code)
        if response.is_error:
            raise decode_error(response)
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

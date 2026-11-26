"""One authenticated connection to ``api.printify.com``, shared by both halves
of the client.

Error decoding leans on a shape this API keeps to without exception -- every
failure observed against the live API is

    {"status": "error", "code": 8251, "message": "Validation failed.",
     "errors": {"reason": "...", "code": 8251}}

``errors.reason`` is a human sentence naming the offending field, and is the
only part of that envelope worth putting in front of a user
(docs/research/api-findings.md).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from etsy_listings.core.clients.retry import DEFAULT_POLICY, RetryPolicy, with_retries
from etsy_listings.core.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.core.errors import UserFacingError

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
    because the fix is a specific human action rather than a retry."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Printify rejected the request ({status_code}).\n"
            f"  Check {PRINTIFY_TOKEN_VAR} in your workspace's .env -- if the token is "
            f"present, it is expired, revoked, or missing a scope.\n"
            f"  Reading the catalog needs `catalog.read`; writing products needs the "
            f"shop and product scopes as well.\n"
            f"  Regenerate it at printify.com/app/account/api (docs/guides/setup.md), "
            f"or re-run `etsy-listings setup`, which verifies a token "
            f"before storing it."
        )


class PrintifyApiError(UserFacingError, RuntimeError):
    """A request Printify understood and refused.

    User-facing for the same reason as :class:`PrintifyAuthError`: a refusal
    the API explained is a refusal the user can read. A 500 is not actionable
    in the same way, but it is still one listing's failure and not the run's
    -- ending the batch on it loses the forty-nine that would have succeeded.

    Carries ``code`` because Printify's numeric codes are stable enough to
    branch on (:data:`WRONG_SHOP_CODE`), and renders ``errors.reason`` because
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

        response = with_retries(send, method, self._policy, sleep=self._sleep)

        if response.status_code in (401, 403):
            raise PrintifyAuthError(response.status_code)
        if response.is_error:
            raise decode_error(response)
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

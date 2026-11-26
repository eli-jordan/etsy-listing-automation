"""One authenticated connection to ``api.printify.com``, shared by both halves of
the client.

Every failure the live API returns is ``{"status": "error", "code": ...,
"message": ..., "errors": {"reason": ..., "code": ...}}``, and only
``errors.reason``, a sentence naming the field, is worth showing a user."""

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
    """A request Printify understood and refused; user-facing, so one listing's failure, a 500
    included, does not end the batch. ``code`` is stable enough to branch on
    (:data:`WRONG_SHOP_CODE`)."""

    def __init__(self, status_code: int, *, code: int | None, reason: str) -> None:
        self.status_code = status_code
        self.code = code
        self.reason = reason
        detail = f" (code {code})" if code is not None else ""
        super().__init__(f"Printify refused the request with {status_code}{detail}: {reason}")


def decode_error(response: httpx.Response) -> PrintifyApiError:
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

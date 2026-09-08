"""Real HTTP implementation of :class:`PrintifyClient` against the shop-scoped
Printify endpoints.

Separate from ``catalog/http.py`` on purpose: that client is pinned to
``/v1/catalog`` and reads only, and the whole value of the split is that
nothing holding a ``CatalogClient`` can reach a call that creates a product.
The token and the host are the same; the authority they carry is not.

Error decoding leans on a shape this API keeps to without exception -- every
failure observed against the live API is

    {"status": "error", "code": 8251, "message": "Validation failed.",
     "errors": {"reason": "...", "code": 8251}}

``errors.reason`` is a human sentence naming the offending field, and is the
only part of that envelope worth putting in front of a user
(docs/api-findings.md).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from etsy_listings.clients.printify.models import Shop
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR

BASE_URL = "https://api.printify.com"
"""No ``/v1`` suffix, unlike the catalog client's: this client addresses
several path families (``/v1/shops``, ``/v1/uploads``) and spelling the
version once per path keeps each call site readable as the documented
endpoint it is."""

TokenSource = str | Callable[[], str]
"""A token, or something that produces one on demand. Resolved lazily for the
same reason the catalog client does it: ``plan`` builds clients it may never
call, and demanding a credential at construction would fail every workspace
that has not reached the phase which needs one."""

DEFAULT_TIMEOUT_SECONDS = 120.0
"""Generous, because uploads travel this client: a print file is megabytes,
and the default 5s timeout turns a slow link into an inscrutable failure."""


class PrintifyAuthError(RuntimeError):
    """Printify rejected the credentials. Distinct from every other failure,
    because the fix is a specific human action rather than a retry."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Printify rejected the request ({status_code}).\n"
            f"  Check {PRINTIFY_TOKEN_VAR} in your workspace's .env -- if the token is "
            f"present, it is expired, revoked, or missing a scope.\n"
            f"  Writing products needs more than `catalog.read`: the token must also "
            f"carry the shop and product scopes.\n"
            f"  Regenerate it at printify.com/app/account/connections, or re-run "
            f"`etsy-listings setup`, which verifies a token before storing it."
        )


class PrintifyApiError(RuntimeError):
    """A request Printify understood and refused.

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


def _decode_error(response: httpx.Response) -> PrintifyApiError:
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


class HttpPrintifyClient(PrintifyClient):
    def __init__(self, token: TokenSource, *, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self._token if isinstance(self._token, str) else self._token()
        response = self._client.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        if response.status_code in (401, 403):
            raise PrintifyAuthError(response.status_code)
        if response.is_error:
            raise _decode_error(response)
        return response

    def shops(self) -> list[Shop]:
        response = self._request("GET", "/v1/shops.json")
        return [Shop.model_validate(item) for item in response.json()]

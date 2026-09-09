"""One authenticated connection to Etsy, and the token endpoint beside it.

Two classes, because Etsy's requests come in two shapes that share almost
nothing:

:class:`Transport` carries **both** credentials -- the app key pair in
``x-api-key`` and the shop owner's bearer -- and is what every listing, image
and shop call goes through. :class:`OAuthClient` talks to the token endpoint,
which takes **neither**: it authenticates by `client_id` in the form body, and
is the only Etsy endpoint that can be called before a token exists. Giving the
token endpoint its own client is what keeps :mod:`tokens` free of a cycle back
through here (A23).

The retry policy, the backoff and the "return the last response rather than
raising" rule are all shared with Printify (A21) -- one `retry.py`, because a
429 means the same thing to both.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from etsy_listings.clients.etsy import oauth
from etsy_listings.clients.etsy.tokens import EtsyAuthError
from etsy_listings.clients.retry import DEFAULT_POLICY, RetryPolicy, with_retries
from etsy_listings.config.secrets import ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR, EtsyAppKey

BASE_URL = "https://openapi.etsy.com"
"""The API reference's documented base URL. Its guides and tutorials use
``api.etsy.com`` for the same paths; both answer, and the reference is the one
that describes the endpoints this transport carries. The OAuth token endpoint
is the exception and keeps the host its own documentation gives it
(:data:`~etsy_listings.clients.etsy.oauth.TOKEN_URL`)."""

DEFAULT_TIMEOUT_SECONDS = 120.0
"""Generous for the same reason Printify's is: listing images travel this
connection, and a 5s default turns a slow uplink into an unreadable failure."""

PING_PATH = "/v3/application/openapi-ping"

BearerSource = Callable[[], str]
"""Resolved per request, never at construction. `plan` builds clients it may
never call, and a workspace that has not signed in must still be able to build
one (A22)."""


class EtsyApiError(RuntimeError):
    """A request Etsy understood and refused.

    Etsy's error envelope is a single ``{"error": "..."}`` string -- no code,
    no field name -- so there is nothing to branch on and the whole value is
    worth showing.
    """

    def __init__(self, status_code: int, *, error: str) -> None:
        self.status_code = status_code
        self.error = error
        super().__init__(f"Etsy refused the request with {status_code}: {error}")


def decode_error(response: httpx.Response) -> EtsyApiError:
    """Pull ``error`` out of the envelope, tolerating its absence.

    A 502 from a proxy is HTML. Failing while decoding the thing that explains
    a failure is the worst moment to fail, so every step degrades to the raw
    body rather than raising.
    """
    detail = response.text.strip() or "no response body"
    try:
        body: Any = response.json()
    except ValueError:
        return EtsyApiError(response.status_code, error=detail)
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        detail = body["error"]
    return EtsyApiError(response.status_code, error=detail)


class Transport:
    """Send a request to Etsy and hand back a response worth reading."""

    def __init__(
        self,
        app_key: EtsyAppKey,
        *,
        bearer: BearerSource | None = None,
        client: httpx.Client | None = None,
        policy: RetryPolicy = DEFAULT_POLICY,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._app_key = app_key
        self._bearer = bearer
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
        self._policy = policy
        self._sleep = sleep

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"x-api-key": self._app_key.header()}
        if self._bearer is not None:
            headers["Authorization"] = f"Bearer {self._bearer()}"

        def send() -> httpx.Response:
            return self._client.request(method, path, headers=headers, **kwargs)

        # Retries first, so a 429 that clears never becomes an exception, and
        # one that does not surfaces as the real decoded error rather than a
        # wrapper's summary of it (A21).
        response = with_retries(send, method, self._policy, sleep=self._sleep)

        if response.status_code in (401, 403):
            raise EtsyAuthError(_rejected_message(response.status_code, bearer=self._bearer))
        if response.is_error:
            raise decode_error(response)
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    def ping(self) -> int:
        """Verify the app key pair alone, and return the application id.

        The one Etsy endpoint that needs no bearer, which makes it exactly the
        check `auth` wants before it opens a browser: a bad keystring or a
        mistyped shared secret is caught at the question that asked for it,
        not three steps later in a redirect nobody can read.
        """
        body: Any = self.get(PING_PATH).json()
        if not isinstance(body, dict) or not isinstance(body.get("application_id"), int):
            raise EtsyApiError(200, error="ping did not return an application_id")
        return int(body["application_id"])


def _rejected_message(status_code: int, *, bearer: BearerSource | None) -> str:
    """Name the credential that was actually rejected.

    Etsy answers 401 for a bad app key pair and for a bad bearer alike, and
    the fixes are different enough -- re-paste two strings, or sign in again
    -- that a message covering both helps nobody. Which credentials the
    request carried is the only distinction available here, so it is the one
    the message draws.
    """
    if bearer is None:
        return (
            f"Etsy rejected the app key pair ({status_code}). Check "
            f"{ETSY_KEYSTRING_VAR} and {ETSY_SHARED_SECRET_VAR} in your workspace's .env."
        )
    return (
        f"Etsy rejected the request ({status_code}). The app key pair or the stored "
        f"access token is no longer valid."
    )


class OAuthClient:
    """The token endpoint: exchange an authorization code, refresh a pair.

    Form-encoded rather than JSON. Etsy's authentication guide documents
    ``application/x-www-form-urlencoded`` and its quick-start tutorial posts
    JSON; the guide is the specification and the tutorial is an example, so
    the guide wins.
    """

    def __init__(
        self,
        keystring: str,
        *,
        client: httpx.Client | None = None,
        policy: RetryPolicy = DEFAULT_POLICY,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._keystring = keystring
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
        self._policy = policy
        self._sleep = sleep

    def exchange(
        self,
        *,
        code: str,
        verifier: str,
        redirect_uri: str = oauth.REDIRECT_URI,
    ) -> oauth.TokenResponse:
        return self._post(
            oauth.authorization_code_form(
                keystring=self._keystring,
                code=code,
                verifier=verifier,
                redirect_uri=redirect_uri,
            )
        )

    def refresh(self, refresh_token: str) -> oauth.TokenResponse:
        return self._post(
            oauth.refresh_form(keystring=self._keystring, refresh_token=refresh_token)
        )

    def _post(self, form: dict[str, str]) -> oauth.TokenResponse:
        def send() -> httpx.Response:
            return self._client.post(oauth.TOKEN_URL, data=form)

        response = with_retries(send, "POST", self._policy, sleep=self._sleep)
        try:
            body: Any = response.json()
        except ValueError:
            raise oauth.OAuthError(
                f"http_{response.status_code}",
                response.text.strip() or "the token endpoint returned no readable body",
            ) from None
        # `parse` raises on an `error` key whatever the status was, which is
        # the shape that matters: Etsy reports `invalid_grant` with a 400, and
        # the caller needs the reason rather than the number.
        return oauth.TokenResponse.parse(body)

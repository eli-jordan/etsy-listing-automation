"""One authenticated connection to Etsy, and the token endpoint beside it.

Etsy's token endpoint authenticates by ``client_id`` in the form body, not by the
app key pair and bearer :class:`Transport` sends, so :class:`OAuthClient` is
separate."""

from __future__ import annotations

import logging
import random as _random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from etsy_listings.core.clients.etsy import oauth
from etsy_listings.core.clients.etsy.tokens import EtsyAuthError
from etsy_listings.core.clients.retry import DEFAULT_POLICY, RetryPolicy, with_retries
from etsy_listings.core.config.secrets import ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR, EtsyAppKey
from etsy_listings.core.errors import UserFacingError

BASE_URL = "https://openapi.etsy.com"
"""The API reference's documented base URL. Its guides and tutorials use
``api.etsy.com`` for the same paths; both answer, and the reference is the one
that describes the endpoints this transport carries. The OAuth token endpoint
is the exception and keeps the host its own documentation gives it
( :data:`~etsy_listings.core.clients.etsy.oauth.TOKEN_URL`)."""

DEFAULT_TIMEOUT_SECONDS = 120.0
"""Generous for the same reason Printify's is: listing images travel this
connection, and a 5s default turns a slow uplink into an unreadable failure."""

PING_PATH = "/v3/application/openapi-ping"

HTTP_NOT_FOUND = 404

_log = logging.getLogger(__name__)

BearerSource = Callable[[], str | None]
AppKeySource = Callable[[], EtsyAppKey]
"""Resolved per request, never at construction. `plan` builds clients it may
never call, and a workspace that has not signed in must still be able to build
one."""


class EtsyApiError(UserFacingError, RuntimeError):
    """A request Etsy understood and refused; user-facing, so one refused listing is reported rather
    than a batch ended.

    Etsy's envelope is one ``{"error": "..."}`` string. ``message`` replaces it for refusals
    whose own text misdescribes them (the video budget); ``error`` keeps Etsy's words."""

    def __init__(self, status_code: int, *, error: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.error = error
        super().__init__(message or f"Etsy refused the request with {status_code}: {error}")


def _error_detail(response: httpx.Response) -> str:
    detail = response.text.strip() or "no response body"
    try:
        body: Any = response.json()
    except ValueError:
        return detail
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, str) else detail


def decode_error(response: httpx.Response) -> EtsyApiError:
    return EtsyApiError(response.status_code, error=_error_detail(response))


class RateGate:
    """Hold the next call back for a second once a response's
    ``x-remaining-this-second`` is 0; Etsy does not say whether its window is
    fixed or sliding, and a full second is right under either.

    Shared by concurrent calls. One waiter sleeps while holding ``_waiting``
    and the rest block on it, and the deadline only moves later, since
    responses from concurrent calls arrive in any order.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._state = threading.Lock()
        self._waiting = threading.Lock()
        self._resume_at = 0.0

    def wait(self) -> None:
        with self._waiting:
            while (owed := self._owed()) > 0:
                self._sleep(owed)

    def _owed(self) -> float:
        with self._state:
            return self._resume_at - self._clock()

    def observe(self, headers: httpx.Headers) -> None:
        _log.debug(
            "Etsy quota: %s remaining today of %s",
            headers.get("x-remaining-today", "?"),
            headers.get("x-limit-per-day", "?"),
        )
        try:
            remaining = int(headers.get("x-remaining-this-second", ""))
        except ValueError:
            return
        if remaining > 0:
            return
        with self._state:
            self._resume_at = max(self._resume_at, self._clock() + 1.0)


@dataclass(frozen=True)
class Timing:
    sleep: Callable[[float], None] = time.sleep
    random: Callable[[], float] = _random.random
    clock: Callable[[], float] = time.monotonic


class Transport:
    def __init__(
        self,
        app_key: EtsyAppKey | AppKeySource,
        *,
        bearer: BearerSource | None = None,
        client: httpx.Client | None = None,
        policy: RetryPolicy = DEFAULT_POLICY,
        timing: Timing = Timing(),
    ) -> None:
        self._app_key = app_key
        self._bearer = bearer
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
        self._policy = policy
        self._sleep = timing.sleep
        self._random = timing.random
        self._gate = RateGate(clock=timing.clock, sleep=timing.sleep)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        app_key = self._app_key() if callable(self._app_key) else self._app_key
        headers = {"x-api-key": app_key.header()}
        if self._bearer is not None and (token := self._bearer()) is not None:
            headers["Authorization"] = f"Bearer {token}"

        def send() -> httpx.Response:
            # Paced per attempt, so a retry waits its turn like any call.
            self._gate.wait()
            response = self._client.request(method, path, headers=headers, **kwargs)
            self._gate.observe(response.headers)
            return response

        response = with_retries(send, method, self._policy, sleep=self._sleep, random=self._random)

        if response.status_code in (401, 403):
            raise EtsyAuthError(
                _rejected_message(
                    response.status_code, bearer=self._bearer, detail=_error_detail(response)
                )
            )
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
        body: Any = self.get(PING_PATH).json()
        if not isinstance(body, dict) or not isinstance(body.get("application_id"), int):
            raise EtsyApiError(200, error="ping did not return an application_id")
        return int(body["application_id"])


def _rejected_message(status_code: int, *, bearer: BearerSource | None, detail: str) -> str:
    """Name the credential that was rejected, with Etsy's own text: Etsy
    answers 401 for a bad key pair, bearer and missing scope alike."""
    if bearer is None:
        return (
            f"Etsy rejected the app key pair ({status_code}): {detail}. Check "
            f"{ETSY_KEYSTRING_VAR} and {ETSY_SHARED_SECRET_VAR} in your workspace's .env."
        )
    return (
        f"Etsy rejected the request ({status_code}): {detail}. If this names a missing "
        f"scope, `etsy-listings auth` grants it on the next sign-in; otherwise the app "
        f"key pair or the stored access token is no longer valid."
    )


class OAuthClient:
    """The token endpoint: exchange an authorization code, refresh a pair.
    Form-encoded, as Etsy's authentication guide documents (its tutorial posts JSON).
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
        # Not status-checked: Etsy reports `invalid_grant` as a 400 with a body.
        return oauth.TokenResponse.parse(body)


def results_of(body: Any) -> list[Any]:
    """The ``results`` of Etsy's ``{count, results}`` list envelope; anything
    else reads as empty, so "nothing listed" and an unexpected shape are
    handled alike."""
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        return list(body["results"])
    return []

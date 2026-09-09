"""Etsy's OAuth 2.0 authorization-code flow, as pure functions.

No I/O, no clock, no globals: this module builds strings and parses payloads,
which is what lets the whole flow be tested without a browser, a socket or a
recorded response. What talks to the network lives in :mod:`transport`, what
catches the redirect lives in :mod:`callback`, and what remembers the result
lives in :mod:`tokens` (A23).

Two facts about Etsy shape everything here:

- **PKCE is mandatory on every flow.** Not an option we chose for hygiene --
  ``code_challenge`` is a required parameter of the authorize request, so the
  verifier has to outlive the browser round trip.
- **The redirect URI must match a pre-registered string exactly**, character
  for character: scheme, host, port, path, no trailing slash. That is why
  :data:`REDIRECT_URI` is a constant rather than something assembled from a
  port number at call time -- the registered string is the source of truth,
  and :mod:`callback` takes its port and path *from* it rather than the other
  way round (PRD 50).
"""

from __future__ import annotations

import base64
import hashlib
import secrets as _secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"

TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
"""``api.etsy.com``, not the ``openapi.etsy.com`` the API reference gives as
its base URL. Etsy's own documentation spells the token endpoint this way in
both the authentication guide and the quick-start tutorial, and the OAuth
endpoints are the one path family the reference does not cover."""

REDIRECT_URI = "http://localhost:8517/oauth/callback"
"""Registered verbatim with the Etsy app. `http` on loopback: Etsy's
authentication guide says redirect URIs must be `https://`, while Etsy's own
quick-start tutorial uses `http://localhost:3003/oauth/redirect` throughout.
The tutorial is the one that has been run (PRD 50)."""

SCOPES: tuple[str, ...] = ("listings_r", "listings_w", "shops_r")
"""The smallest set covering Phases 3-6. `listings_w` covers image upload
*and* delete; `listings_d` is for deleting listings, which this tool never
does. Changing this forces every user through the browser again, so it is a
decision (PRD 50) rather than a default."""

VERIFIER_BYTES = 32
"""32 random bytes is 43 base64url characters -- the shortest verifier RFC
7636 allows, and what Etsy's own example generator produces."""

STATE_BYTES = 16


class OAuthError(RuntimeError):
    """Etsy refused, or answered with something this module cannot read.

    One class for both, because the caller's response is the same either way:
    tell the user what Etsy said and stop. The distinction that *does* matter
    -- whether re-running `auth` can fix it -- is :attr:`is_grant_failure`.
    """

    def __init__(self, error: str, description: str | None = None) -> None:
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}" if description else error)

    @property
    def is_grant_failure(self) -> bool:
        """True when the *grant* was rejected rather than the request.

        `invalid_grant` is what a used authorization code, an expired refresh
        token and a revoked consent all come back as, and it is the one error
        whose answer is "run `auth` again" rather than "look at the code".
        """
        return self.error == "invalid_grant"


@dataclass(frozen=True)
class Pkce:
    """A verifier and the challenge derived from it.

    Kept together because they are only ever meaningful as a pair: the
    challenge goes to the browser, the verifier is held back and proves, at
    token exchange, that the same client started the flow.
    """

    verifier: str
    challenge: str

    @classmethod
    def generate(cls, *, entropy: Callable[[int], bytes] = _secrets.token_bytes) -> Pkce:
        verifier = _b64url(entropy(VERIFIER_BYTES))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        return cls(verifier=verifier, challenge=challenge)


def new_state(*, entropy: Callable[[int], bytes] = _secrets.token_bytes) -> str:
    """A single-use value Etsy echoes back, so the redirect can be tied to the
    request that started it."""
    return _b64url(entropy(STATE_BYTES))


def authorize_url(
    *,
    keystring: str,
    pkce: Pkce,
    state: str,
    redirect_uri: str = REDIRECT_URI,
    scopes: Sequence[str] = SCOPES,
) -> str:
    """The URL to open in the browser.

    Encoded to match Etsy's documented example rather than to `urlencode`'s
    defaults, which are wrong here in two ways. Spaces between scopes become
    `+`, and Etsy documents `%20` -- whether its authorize endpoint decodes a
    `+` as a space is not something to discover on a user's consent screen.
    And the redirect URI comes out fully escaped, where every Etsy example
    shows it plain; since the URI is compared against a registered string,
    the encoding that appears in the documentation is the one worth sending.
    """
    query = urlencode(
        {
            "response_type": "code",
            "client_id": keystring,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
        },
        quote_via=quote,
        safe=":/",
    )
    return f"{AUTHORIZE_URL}?{query}"


def check_state(*, sent: str, received: str | None) -> None:
    """Raise unless the redirect carried back the state we sent.

    A mismatch is not a glitch to log and continue past: it means the redirect
    being processed belongs to a request this process did not make, which is
    the CSRF case `state` exists to catch.
    """
    if received != sent:
        raise OAuthError(
            "state_mismatch",
            "the redirect did not carry back the value this flow sent. Nothing was "
            "stored. Run `auth` again, and do not reuse an old browser tab.",
        )


def authorization_code_form(
    *,
    keystring: str,
    code: str,
    verifier: str,
    redirect_uri: str = REDIRECT_URI,
) -> dict[str, str]:
    return {
        "grant_type": "authorization_code",
        "client_id": keystring,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": verifier,
    }


def refresh_form(*, keystring: str, refresh_token: str) -> dict[str, str]:
    """No `redirect_uri` and no verifier: a refresh grant carries neither, and
    sending them is how a working refresh starts failing after a callback
    change."""
    return {
        "grant_type": "refresh_token",
        "client_id": keystring,
        "refresh_token": refresh_token,
    }


@dataclass(frozen=True)
class TokenResponse:
    """A successful answer from the token endpoint, whichever grant asked.

    Both grants return the same shape, including a **new refresh token every
    time** -- rotation is not an occasional event to handle, it is the normal
    case (A23).
    """

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str

    @property
    def user_id(self) -> int:
        """The numeric prefix Etsy puts on its tokens.

        It is the shop owner's user id, and the only place the flow yields one
        without a further request. `int()` on a token that has drifted from
        that format raises rather than guessing -- the alternative is a
        plausible-looking id in a URL path.
        """
        prefix, _, _ = self.access_token.partition(".")
        try:
            return int(prefix)
        except ValueError as exc:
            raise OAuthError(
                "unexpected_token_format",
                "Etsy's access token did not start with the documented user-id prefix.",
            ) from exc

    @classmethod
    def parse(cls, payload: Any) -> TokenResponse:
        if not isinstance(payload, dict):
            raise OAuthError("unexpected_response", "the token endpoint did not return an object.")
        if "error" in payload:
            raise OAuthError(
                str(payload.get("error")),
                _optional_str(payload.get("error_description")),
            )
        try:
            return cls(
                access_token=_require_str(payload, "access_token"),
                refresh_token=_require_str(payload, "refresh_token"),
                expires_in=int(payload["expires_in"]),
                # A token exchange always reports its scopes; a token-exchange
                # grant (OAuth 1.0 migration) documents no `scope` at all, so
                # its absence is recorded as unknown rather than refused.
                scope=_optional_str(payload.get("scope")) or "",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OAuthError(
                "unexpected_response",
                f"the token endpoint's answer was missing or malformed: {exc}",
            ) from exc


def _b64url(raw: bytes) -> str:
    """Unpadded base64url -- the only alphabet RFC 7636 permits for a verifier,
    and the one Etsy's `code_challenge` is compared in."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} was not a non-empty string")
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

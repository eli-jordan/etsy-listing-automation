"""Etsy's OAuth 2.0 authorization-code flow, as pure functions: no I/O, no clock,
no globals.

Etsy requires PKCE on every flow and compares the redirect URI exactly, so
:data:`REDIRECT_URI` is the constant :mod:`callback` takes its port and path
from."""

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
The tutorial is the one that has been run."""

SCOPES: tuple[str, ...] = ("listings_r", "listings_w", "shops_r", "shops_w")
"""The smallest set covering Phases 3-6. `shops_w` lets the editor create a
shop section inline; it does not broaden the tool into managing
shipping profiles. `listings_w` covers image upload and delete;
`listings_d` is for deleting listings, which this tool never does. Changing
this forces every user through the browser again, so it is a decision rather than a default."""

VERIFIER_BYTES = 32
"""32 random bytes is 43 base64url characters -- the shortest verifier RFC
7636 allows, and what Etsy's own example generator produces."""

STATE_BYTES = 16


class OAuthError(RuntimeError):
    """Etsy refused, or answered with something this module cannot read;
    :attr:`is_grant_failure` says whether re-running `auth` can fix it."""

    def __init__(self, error: str, description: str | None = None) -> None:
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}" if description else error)

    @property
    def is_grant_failure(self) -> bool:
        return self.error == "invalid_grant"


@dataclass(frozen=True)
class Pkce:
    """A verifier and the challenge derived from it."""

    verifier: str
    challenge: str

    @classmethod
    def generate(cls, *, entropy: Callable[[int], bytes] = _secrets.token_bytes) -> Pkce:
        verifier = _b64url(entropy(VERIFIER_BYTES))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        return cls(verifier=verifier, challenge=challenge)


def new_state(*, entropy: Callable[[int], bytes] = _secrets.token_bytes) -> str:
    return _b64url(entropy(STATE_BYTES))


def authorize_url(
    *,
    keystring: str,
    pkce: Pkce,
    state: str,
    redirect_uri: str = REDIRECT_URI,
    scopes: Sequence[str] = SCOPES,
) -> str:
    """The URL to open in the browser, encoded as Etsy's documented example
    is (``%20`` between scopes, the redirect URI unescaped), not as
    ``urlencode``'s defaults would."""
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
    """A refresh grant carries no `redirect_uri` and no verifier."""
    return {
        "grant_type": "refresh_token",
        "client_id": keystring,
        "refresh_token": refresh_token,
    }


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str

    @property
    def user_id(self) -> int:
        """The shop owner's user id: Etsy's numeric prefix on its tokens."""
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
    """Unpadded base64url, the alphabet RFC 7636 permits for a verifier."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} was not a non-empty string")
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

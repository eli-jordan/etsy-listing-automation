"""An Etsy grant that rotates its refresh token on every use, as Etsy does.

Two stand-ins for the token endpoint share one rule: the current refresh
token buys a new pair and is spent, a spent or revoked one is answered with
``invalid_grant``. :meth:`RotatingGrant.refresh` is a ``TokenStore`` refresh
callable; :meth:`RotatingGrant.answer` is the same endpoint over HTTP, for a
test that keeps the production client wiring. ``hold`` gates the first
successful rotation before its answer is returned, which is the window in
which a second refresher of the same grant would spend it twice.
"""

from __future__ import annotations

import json
import threading
from urllib.parse import parse_qs

import httpx

from etsy_listings.core.clients.etsy.oauth import OAuthError, TokenResponse

from tests.support.gates import Gate

USER_ID = 12345678


class RotatingGrant:
    def __init__(self, refresh_token: str, *, hold: Gate | None = None) -> None:
        self.current: str | None = refresh_token
        self.hold = hold
        self.rotations = 0
        self.refused = 0
        self._guard = threading.Lock()

    def revoke(self) -> None:
        """The seller withdrew consent: no refresh token works any more."""
        self.current = None

    def refresh(self, refresh_token: str) -> TokenResponse:
        with self._guard:
            if refresh_token != self.current:
                self.refused += 1
                raise OAuthError("invalid_grant", "Refresh token is invalid or expired")
            self.rotations += 1
            n = self.rotations
            self.current = f"{USER_ID}.refresh-{n}"
            gate, self.hold = self.hold, None
        if gate is not None:
            gate.hold()
        return TokenResponse(
            access_token=f"{USER_ID}.access-{n}",
            refresh_token=f"{USER_ID}.refresh-{n}",
            expires_in=3600,
            scope="listings_r listings_w shops_r shops_w",
        )

    def answer(self, request: httpx.Request) -> httpx.Response:
        """The token endpoint's reply to a form-encoded refresh POST."""
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        try:
            pair = self.refresh(form["refresh_token"])
        except OAuthError as exc:
            body = {"error": exc.error, "error_description": exc.description}
            return httpx.Response(400, content=json.dumps(body))
        return httpx.Response(
            200,
            json={
                "access_token": pair.access_token,
                "refresh_token": pair.refresh_token,
                "expires_in": pair.expires_in,
                "token_type": "Bearer",
                "scope": pair.scope,
            },
        )

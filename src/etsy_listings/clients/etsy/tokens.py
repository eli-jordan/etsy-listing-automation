"""The OAuth tokens on disk, and the only code that rotates them.

Etsy issues a new **refresh** token on every refresh, so the file write is
part of the protocol rather than a cache of it: lose the write and the next
run has no way back to a working credential except the browser. Everything
here follows from that (A23).

- The write is **atomic and lands before the new access token is used**, so a
  crash mid-rotation leaves either the old pair or the new one, never a
  half-file and never a rotated-but-unrecorded token.
- Refresh is **serialised in-process**, because `plan` fans its read-only
  fetches across a thread pool (A3) and two threads refreshing the same token
  would each invalidate the other's.
- An `invalid_grant` is **re-read before it is believed**: a second process
  may have rotated the pair a moment ago, and the answer to that is to use
  what it wrote, not to send the user to a browser.

The store never builds a client. It is handed a `refresh` callable, because
the token endpoint is the one Etsy endpoint that needs no bearer -- which is
what keeps this module free of a cycle through :mod:`transport`.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from etsy_listings.clients.etsy.oauth import OAuthError, TokenResponse
from etsy_listings.errors import UserFacingError

REFRESH_MARGIN = timedelta(minutes=5)
"""How much of an access token's hour is treated as already spent. Long enough
that a run which takes minutes cannot expire mid-way through; short enough
that ordinary use is not refreshing on every command."""

REFRESH_TOKEN_LIFETIME = timedelta(days=90)
"""Etsy documents the refresh token's life and not whether using one restarts
the clock. So this is recomputed at every rotation -- optimistic, and never
the authority: an `invalid_grant` is what actually settles it (PRD 50)."""

RENEW_WARNING = timedelta(days=14)


class EtsyAuthError(UserFacingError, RuntimeError):
    """There is no usable Etsy credential, and no retry will produce one.

    Raised where a token is *needed*, never where one is merely absent, so the
    message can always name the command that fixes it. Also what
    :mod:`transport` raises on a 401: from the caller's side, a rejected token
    and a missing one call for the same next step.

    Naming the command that fixes it is the definition of a
    :class:`~etsy_listings.errors.UserFacingError`; being one is what keeps a
    signed-out workspace reporting that fact per listing rather than aborting
    the run on the first (PRD 16).
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"{detail}\n  Run `etsy-listings auth` to sign in to Etsy again.")


@dataclass(frozen=True)
class StoredTokens:
    """What ``.auth/etsy-tokens.json`` holds.

    Timestamps are absolute and stored as ISO-8601 UTC rather than the
    `expires_in` seconds Etsy sends: a duration is only meaningful next to the
    instant it was received, and this file outlives the process that wrote it.
    Written in a form a human can read, because "when does this expire?" is a
    question the file should be able to answer on its own.
    """

    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime
    scope: str
    user_id: int

    def is_fresh(self, now: datetime, *, margin: timedelta = REFRESH_MARGIN) -> bool:
        return now + margin < self.expires_at

    def refresh_expires_in(self, now: datetime) -> timedelta:
        return self.refresh_expires_at - now

    def to_document(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "scope": self.scope,
            "user_id": self.user_id,
        }

    @classmethod
    def parse(cls, document: Any) -> StoredTokens | None:
        """The stored document, or ``None`` if it cannot be read.

        ``None`` for both "not there" and "will not decode", the same answer
        the lockfile gives for the same reason: a credential file we cannot
        read is one we cannot prove anything about, and guessing at half of it
        is worse than asking the user to sign in again.
        """
        if not isinstance(document, dict):
            return None
        try:
            return cls(
                access_token=str(document["access_token"]),
                refresh_token=str(document["refresh_token"]),
                expires_at=datetime.fromisoformat(str(document["expires_at"])),
                refresh_expires_at=datetime.fromisoformat(str(document["refresh_expires_at"])),
                scope=str(document.get("scope", "")),
                user_id=int(document["user_id"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def from_response(cls, response: TokenResponse, *, now: datetime) -> StoredTokens:
        return cls(
            access_token=response.access_token,
            refresh_token=response.refresh_token,
            expires_at=now + timedelta(seconds=response.expires_in),
            refresh_expires_at=now + REFRESH_TOKEN_LIFETIME,
            scope=response.scope,
            user_id=response.user_id,
        )


RefreshFn = Callable[[str], TokenResponse]
"""Exchanges a refresh token for a new pair. Injected rather than imported so
this module needs no HTTP client, and so the whole rotation story can be
tested without one."""


def utcnow() -> datetime:
    return datetime.now(UTC)


class TokenStore:
    """Reads, refreshes and writes the token file. The only writer of it."""

    def __init__(
        self,
        path: Path,
        *,
        refresh: RefreshFn,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._path = path
        self._refresh = refresh
        self._now = now
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> StoredTokens | None:
        """What is on disk, without refreshing anything.

        For `auth --check` and for the wizard's "you are already signed in" --
        the questions that want the stored state rather than a usable token.
        """
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            document = json.loads(raw)
        except ValueError:
            return None
        return StoredTokens.parse(document)

    def save(self, tokens: StoredTokens) -> None:
        """Write atomically, then tighten the mode as far as the platform
        allows.

        `os.replace` over a temp file in the same directory is the write; the
        `chmod` is best-effort and deliberately not checked. On Windows -- the
        platform this is developed on -- it sets a read-only bit and is not an
        access control at all, so failing the run over it would be enforcing a
        guarantee we cannot make either way (PRD 49).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_name(self._path.name + ".tmp")
        temp.write_text(json.dumps(tokens.to_document(), indent=2) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(temp, 0o600)
        os.replace(temp, self._path)

    def record(self, response: TokenResponse) -> StoredTokens:
        """Store the result of a fresh authorization-code grant."""
        tokens = StoredTokens.from_response(response, now=self._now())
        self.save(tokens)
        return tokens

    def access_token(self) -> str:
        """A token good for the next few minutes, refreshing if needed.

        This is the callable the transport is built with, and it is resolved
        lazily on every request rather than once at construction -- `plan`
        builds clients it may never call, and a workspace that has not reached
        Phase 3 must not be made to sign in to build one (A22).
        """
        with self._lock:
            stored = self.load()
            if stored is None:
                raise EtsyAuthError(f"No Etsy tokens in {self._path}.")
            now = self._now()
            if stored.is_fresh(now):
                return stored.access_token
            return self._rotate(stored).access_token

    def _rotate(self, stored: StoredTokens) -> StoredTokens:
        """Exchange the refresh token, tolerating a rotation we did not make.

        The re-read is the whole point: two runs in parallel each hold a pair,
        the first rotates, and the second's `invalid_grant` means "you are
        holding yesterday's token", not "the user must sign in". Re-reading
        answers which of the two it was, and only a genuinely dead grant
        reaches the user.
        """
        try:
            response = self._refresh(stored.refresh_token)
        except OAuthError as exc:
            if not exc.is_grant_failure:
                raise
            current = self.load()
            if current is not None and current.refresh_token != stored.refresh_token:
                if current.is_fresh(self._now()):
                    return current
                return self._rotate(current)
            raise EtsyAuthError(
                f"Etsy rejected the stored refresh token ({exc.error}). It has expired "
                f"after 90 days, or consent was withdrawn."
            ) from exc

        rotated = StoredTokens.from_response(response, now=self._now())
        # Saved before it is returned, never after: a caller that used a token
        # this process failed to record would leave the file naming a refresh
        # token Etsy has already retired.
        self.save(rotated)
        return rotated

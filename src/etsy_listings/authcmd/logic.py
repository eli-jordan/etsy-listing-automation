"""What ``auth`` knows, as functions of its inputs.

Everything here answers a question about credentials that already exist --
which are missing, how long the Etsy consent has left, whether that is worth
warning about. Sequencing the questions and doing the I/O is
:mod:`interactive`'s job, the same split ``setup`` uses and for the same
reason: the ordering of prompts is the one part no test can drive cheaply, so
as little as possible belongs there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from etsy_listings.clients.etsy.tokens import RENEW_WARNING, StoredTokens
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    Secrets,
)

REQUIRED_VARS: tuple[str, ...] = (
    PRINTIFY_TOKEN_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
)
"""The credentials without which some command fails. The Anthropic key is not
among them: nothing before Phase 4 asks for one, and treating it as required
would make every `auth --check` report a workspace as incomplete for a feature
it does not have yet."""


@dataclass(frozen=True)
class TokenSummary:
    """The stored Etsy consent, in the terms a user asks about it.

    Two lifetimes, not one, because they fail differently. An expired *access*
    token is invisible -- the next run refreshes it. An expired *refresh*
    token is a browser trip, and the only warning a user can act on.
    """

    present: bool
    user_id: int | None = None
    access_valid: bool = False
    refresh_days: int | None = None
    scope: str = ""

    def line(self) -> str:
        if not self.present:
            return "Etsy sign-in: none stored"
        access = "valid" if self.access_valid else "expired (refreshed on next use)"
        return (
            f"Etsy sign-in: user {self.user_id}, access token {access}, "
            f"consent good for {self.refresh_days} more days"
        )


def summarise(stored: StoredTokens | None, *, now: datetime) -> TokenSummary:
    if stored is None:
        return TokenSummary(present=False)
    remaining = stored.refresh_expires_in(now)
    return TokenSummary(
        present=True,
        user_id=stored.user_id,
        access_valid=stored.is_fresh(now),
        # Rounded down, and floored at zero: "0 days" is a truthful thing to
        # say about a consent that expired last week, and a negative number
        # invites a reader to work out what it means.
        refresh_days=max(0, remaining.days),
        scope=stored.scope,
    )


def renewal_warning(summary: TokenSummary) -> str | None:
    """The line to print when the 90-day clock is nearly up, or ``None``.

    Only ever a warning, never a refusal: the credential still works, and a
    command that stopped working two weeks early to protect the user from
    something that has not happened would be worse than the thing it prevents.
    """
    if not summary.present or summary.refresh_days is None:
        return None
    if summary.refresh_days > RENEW_WARNING.days:
        return None
    return (
        f"Etsy consent expires in {summary.refresh_days} days. "
        f"Run `etsy-listings auth` before then to renew it without interrupting a run."
    )


def missing_credentials(secrets: Secrets) -> tuple[str, ...]:
    """Which of :data:`REQUIRED_VARS` this workspace cannot supply."""
    have = {
        PRINTIFY_TOKEN_VAR: secrets.printify_api_token,
        ETSY_KEYSTRING_VAR: secrets.etsy_keystring,
        ETSY_SHARED_SECRET_VAR: secrets.etsy_shared_secret,
    }
    return tuple(name for name in REQUIRED_VARS if not have[name])


def optional_credentials(secrets: Secrets) -> tuple[str, ...]:
    return () if secrets.anthropic_api_key else (ANTHROPIC_KEY_VAR,)

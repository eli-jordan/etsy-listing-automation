"""Credential operations: where one is, proving it, storing it, and what a
workspace's credentials add up to.

The terminal-free half of what ``auth`` and ``setup`` do with a credential
(ADR-0025: credentials are ``auth``'s, ids ``setup``'s). Asking for one,
saying what was proved and refusing with a command to re-run are the CLI's
(``cli/credentials.py``); everything here takes its clients as arguments and
answers with values or the client's own error, so it runs without a terminal
or a socket.

**Proving is not storing**, and they are separate on purpose. ``auth`` stores
each credential as it is proved, because its parts are independent and a
working Printify token should survive abandoning the Etsy sign-in. ``setup``
stores at the very end, after every question is answered, because a token
left behind by a cancelled run is a workspace that looks configured and is
not. One order is right for each, and neither is right for both -- so no
operation here combines them.

The Etsy sign-in is split the same way (ADR-0026, ADR-0027): building the
consent URL and completing the grant from a redirect are here; opening a
browser and waiting on the loopback callback are the caller's, because the
first is a human step and the second is the clients' own
(:mod:`~etsy_listings.core.clients.etsy.callback`).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy import oauth
from etsy_listings.core.clients.etsy.callback import Callback
from etsy_listings.core.clients.etsy.oauth import TokenResponse
from etsy_listings.core.clients.etsy.tokens import RENEW_WARNING, StoredTokens, TokenStore
from etsy_listings.core.clients.etsy.transport import Transport
from etsy_listings.core.clients.printify.models import Shop
from etsy_listings.core.clients.printify.protocol import PrintifyClient
from etsy_listings.core.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    EtsyAppKey,
    Secrets,
)
from etsy_listings.core.workspace import layout, scaffold

# ---------------------------------------------------------------- credentials


@dataclass(frozen=True)
class Credential:
    """One credential, as the environment variables that hold it.

    A key *pair* is one credential of two variables, because both halves ride
    on one header and a verification cannot say which of them was wrong.
    """

    variables: tuple[str, ...]
    optional: bool = False
    """Whether a blank answer is a complete step rather than a missing value.
    True only for a credential nothing needs yet."""


PRINTIFY = Credential((PRINTIFY_TOKEN_VAR,))
ETSY_APP_KEY = Credential((ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR))
ANTHROPIC = Credential((ANTHROPIC_KEY_VAR,), optional=True)


def stored(root: Path, variable: str) -> str | None:
    """A credential this machine already has, environment first.

    :class:`~etsy_listings.core.config.secrets.Secrets`' own precedence, so a
    wizard cannot disagree with the rest of the tool about which credential
    is in play: one that stores a token the next command then ignores is
    worse than one that never ran.
    """
    from_env = os.environ.get(variable)
    if from_env:
        return from_env
    secrets = Secrets.load(root / layout.ENV_FILE)
    return {
        PRINTIFY_TOKEN_VAR: secrets.printify_api_token,
        ETSY_KEYSTRING_VAR: secrets.etsy_keystring,
        ETSY_SHARED_SECRET_VAR: secrets.etsy_shared_secret,
        ANTHROPIC_KEY_VAR: secrets.anthropic_api_key,
    }[variable]


def stored_values(root: Path, credential: Credential) -> tuple[str | None, ...]:
    """Each of ``credential``'s variables as :func:`stored` finds it.

    Half a pair comes back half present, so a caller can keep the half it has
    and ask only for the rest.
    """
    return tuple(stored(root, variable) for variable in credential.variables)


def store(root: Path, credential: Credential, values: tuple[str, ...]) -> None:
    """Write ``values`` -- parallel to ``credential.variables`` -- into the
    workspace's ``.env``, leaving every other line alone.

    Writes nothing for a blank optional credential: there is nothing to keep.
    A blank *required* value is refused with :class:`ValueError` rather than
    written, because an empty line in ``.env`` reads as configured to nobody.
    """
    if len(values) != len(credential.variables):
        raise ValueError(
            f"{len(values)} value(s) for {len(credential.variables)} variable(s): "
            f"{', '.join(credential.variables)}"
        )
    if credential.optional and not any(value.strip() for value in values):
        return
    blank = [v for v, value in zip(credential.variables, values, strict=True) if not value.strip()]
    if blank:
        raise ValueError(f"refusing to store a blank {', '.join(blank)}")
    for variable, value in zip(credential.variables, values, strict=True):
        scaffold.write_env_value(root, variable, value)


# --------------------------------------------------------------- verification


def verify_printify_token(
    token: str,
    *,
    client_for: Callable[[str], PrintifyClient] = connections.printify_client_for,
) -> list[Shop]:
    """The shops ``token`` reaches; raises ``PrintifyAuthError`` if it reaches none.

    The proof *is* the shop list -- ``setup`` needs exactly that answer -- so
    verification hands it back rather than a boolean, and nobody makes the
    same call twice. The client is built from the token in hand, not from
    ``.env``, because an unverified token is deliberately not stored yet.
    """
    return client_for(token).shops()


class _Pingable(Protocol):
    def ping(self) -> int: ...


def verify_etsy_app_key(
    app_key: EtsyAppKey,
    *,
    transport_for: Callable[[EtsyAppKey], _Pingable] = Transport,
) -> int:
    """The Etsy application id both halves of ``app_key`` identify.

    One ping proves the pair together: ``x-api-key`` carries them joined, so
    Etsy cannot say which half was wrong and this does not pretend to.
    """
    return transport_for(app_key).ping()


# --------------------------------------------------------------------- status

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

    @property
    def renewal_due(self) -> bool:
        """Whether the 90-day consent is close enough to its end to say so.

        Only ever worth a warning, never a refusal: the credential still
        works, and a command that stopped working two weeks early to protect
        the user from something that has not happened would be worse than
        the thing it prevents.
        """
        return (
            self.present
            and self.refresh_days is not None
            and (self.refresh_days <= RENEW_WARNING.days)
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


@dataclass(frozen=True)
class CredentialStatus:
    """Everything ``auth --check`` reports, read without writing anything."""

    sign_in: TokenSummary
    missing: tuple[str, ...]
    optional_missing: tuple[str, ...]
    env_file: Path


def credential_status(root: Path, *, tokens: TokenStore, now: datetime) -> CredentialStatus:
    """What this workspace holds -- including a workspace with no ``shop.yaml``
    and no credentials at all, which is when the question is most often asked.

    Reads the token file without refreshing it: "am I still signed in?" must
    never be a question you risk rotating a refresh token to ask (ADR-0027).
    """
    secrets = Secrets.load(root / layout.ENV_FILE)
    return CredentialStatus(
        sign_in=summarise(tokens.load(), now=now),
        missing=missing_credentials(secrets),
        optional_missing=optional_credentials(secrets),
        env_file=secrets.env_file,
    )


# --------------------------------------------------------------- Etsy sign-in


@dataclass(frozen=True)
class EtsySignIn:
    """One consent request: the URL a human opens, and what checks its answer."""

    url: str
    pkce: oauth.Pkce
    state: str


def begin_etsy_sign_in(app_key: EtsyAppKey) -> EtsySignIn:
    """A fresh PKCE pair and ``state``, and the consent URL carrying them.

    Every scope this tool uses, at the one registered loopback callback
    (ADR-0026). Opening the URL is the caller's: it is a human step.
    """
    pkce = oauth.Pkce.generate()
    state = oauth.new_state()
    url = oauth.authorize_url(keystring=app_key.keystring, pkce=pkce, state=state)
    return EtsySignIn(url=url, pkce=pkce, state=state)


class _CodeExchange(Protocol):
    def exchange(self, *, code: str, verifier: str) -> TokenResponse: ...


@dataclass(frozen=True)
class SignedIn:
    tokens: StoredTokens
    granted_every_scope: bool
    """False when Etsy silently granted a subset -- an app registration that
    allows less than was asked. The shortfall only shows up later as a 403 on
    one endpoint, so it is cheaper to report now."""


def complete_etsy_sign_in(
    sign_in: EtsySignIn,
    redirect: Callback,
    *,
    oauth_client: _CodeExchange,
    tokens: TokenStore,
) -> SignedIn:
    """Exchange the redirect's code and persist the tokens it buys.

    A redirect that did not carry back this request's ``state`` raises
    ``OAuthError`` before anything is exchanged or written: it belongs to a
    request this process did not make. The tokens are persisted before they
    are returned, so nothing can use a grant that is not on disk (ADR-0027).
    """
    oauth.check_state(sent=sign_in.state, received=redirect.state)
    response = oauth_client.exchange(code=redirect.code, verifier=sign_in.pkce.verifier)
    recorded = tokens.record(response)
    return SignedIn(tokens=recorded, granted_every_scope=recorded.scope == " ".join(oauth.SCOPES))

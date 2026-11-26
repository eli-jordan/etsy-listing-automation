"""Credential operations: where one is, proving it, storing it, and what a
workspace's credentials add up to; the terminal-free half of ``auth`` and
``setup``. Proving and storing stay separate operations (architecture,
*Workspace, credentials and prompts*).
"""

from __future__ import annotations

import json
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
    BACKUP_PASSWORD_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    EtsyAppKey,
    Secrets,
)
from etsy_listings.core.workspace import layout, scaffold


@dataclass(frozen=True)
class Credential:
    """One credential, as the environment variables that hold it. Etsy's key
    pair is one: both halves ride on one header, so a failed verification
    cannot say which half was wrong.
    """

    variables: tuple[str, ...]


PRINTIFY = Credential((PRINTIFY_TOKEN_VAR,))
ETSY_APP_KEY = Credential((ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR))
BACKUP_PASSWORD = Credential((BACKUP_PASSWORD_VAR,))


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
        BACKUP_PASSWORD_VAR: secrets.backup_password,
    }[variable]


def stored_values(root: Path, credential: Credential) -> tuple[str | None, ...]:
    """Each of ``credential``'s variables as :func:`stored` finds it."""
    return tuple(stored(root, variable) for variable in credential.variables)


def store(root: Path, credential: Credential, values: tuple[str, ...]) -> None:
    """Write ``values`` -- parallel to ``credential.variables`` -- into the
    workspace's ``.env``, leaving every other line alone."""
    if len(values) != len(credential.variables):
        raise ValueError(
            f"{len(values)} value(s) for {len(credential.variables)} variable(s): "
            f"{', '.join(credential.variables)}"
        )
    blank = [v for v, value in zip(credential.variables, values, strict=True) if not value.strip()]
    if blank:
        raise ValueError(f"refusing to store a blank {', '.join(blank)}")
    for variable, value in zip(credential.variables, values, strict=True):
        scaffold.write_env_value(root, variable, _env_value(variable, value))


def _env_value(variable: str, value: str) -> str:
    if variable != BACKUP_PASSWORD_VAR:
        return value
    if value == value.strip() and not any(char in value for char in "#\"'\r\n"):
        return value
    return json.dumps(value, ensure_ascii=False)


def verify_printify_token(
    token: str,
    *,
    client_for: Callable[[str], PrintifyClient] = connections.printify_client_for,
) -> list[Shop]:
    """The shops ``token`` reaches; raises ``PrintifyAuthError`` if it reaches none."""
    return client_for(token).shops()


class _Pingable(Protocol):
    def ping(self) -> int: ...


def verify_etsy_app_key(
    app_key: EtsyAppKey,
    *,
    transport_for: Callable[[EtsyAppKey], _Pingable] = Transport,
) -> int:
    return transport_for(app_key).ping()


REQUIRED_VARS: tuple[str, ...] = (
    PRINTIFY_TOKEN_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
)


@dataclass(frozen=True)
class TokenSummary:
    """The stored Etsy consent: whether the access token is fresh (an expired
    one refreshes unseen) and the whole days left on the refresh token (an
    expired one needs a browser sign-in)."""

    present: bool
    user_id: int | None = None
    access_valid: bool = False
    refresh_days: int | None = None
    scope: str = ""

    @property
    def renewal_due(self) -> bool:
        """Whether the 90-day consent is close enough to its end to warn."""
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
        refresh_days=max(0, remaining.days),
        scope=stored.scope,
    )


def missing_credentials(secrets: Secrets) -> tuple[str, ...]:
    have = {
        PRINTIFY_TOKEN_VAR: secrets.printify_api_token,
        ETSY_KEYSTRING_VAR: secrets.etsy_keystring,
        ETSY_SHARED_SECRET_VAR: secrets.etsy_shared_secret,
    }
    return tuple(name for name in REQUIRED_VARS if not have[name])


@dataclass(frozen=True)
class CredentialStatus:
    sign_in: TokenSummary
    missing: tuple[str, ...]
    env_file: Path


def credential_status(root: Path, *, tokens: TokenStore, now: datetime) -> CredentialStatus:
    """What this workspace holds, even one with no ``shop.yaml``. Reads the
    token file without refreshing it: a refresh rotates the token (ADR-0027)."""
    secrets = Secrets.load(root / layout.ENV_FILE)
    return CredentialStatus(
        sign_in=summarise(tokens.load(), now=now),
        missing=missing_credentials(secrets),
        env_file=secrets.env_file,
    )


@dataclass(frozen=True)
class EtsySignIn:
    url: str
    pkce: oauth.Pkce
    state: str


def begin_etsy_sign_in(app_key: EtsyAppKey) -> EtsySignIn:
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
    oauth.check_state(sent=sign_in.state, received=redirect.state)
    response = oauth_client.exchange(code=redirect.code, verifier=sign_in.pkce.verifier)
    recorded = tokens.record(response)
    return SignedIn(tokens=recorded, granted_every_scope=recorded.scope == " ".join(oauth.SCOPES))

"""Credential operations: where one is, proving it, storing it, and what a
workspace's credentials add up to; the terminal-free half of ``auth`` and
``setup``.
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
    """Etsy's key pair is one credential: both halves ride on one header, so
    a failed verification cannot say which half was wrong."""

    variables: tuple[str, ...]


PRINTIFY = Credential((PRINTIFY_TOKEN_VAR,))
ETSY_APP_KEY = Credential((ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR))
BACKUP_PASSWORD = Credential((BACKUP_PASSWORD_VAR,))


def stored(root: Path, variable: str) -> str | None:
    """Environment first, as :class:`Secrets` resolves it, so a wizard never
    stores a token the next command ignores."""
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
    return tuple(stored(root, variable) for variable in credential.variables)


def store(root: Path, credential: Credential, values: tuple[str, ...]) -> None:
    """Leaves every other ``.env`` line alone."""
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
    """An expired access token refreshes unseen; an expired refresh token
    needs a browser sign-in."""

    present: bool
    user_id: int | None = None
    access_valid: bool = False
    refresh_days: int | None = None
    scope: str = ""

    @property
    def renewal_due(self) -> bool:
        """Etsy's consent lasts 90 days."""
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
    """Reads the token file without refreshing it: a refresh rotates the
    token (ADR-0027)."""
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
    """Etsy silently grants a subset when the app registration allows less;
    unreported, it shows up later as a 403 on one endpoint."""


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

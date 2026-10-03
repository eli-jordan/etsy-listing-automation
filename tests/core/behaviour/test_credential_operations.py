"""Credential operations, called directly: no Typer, no prompt, no terminal.

Where a credential already is, how one is proved and stored, what a
workspace's credentials add up to, and the non-terminal half of the Etsy
sign-in. Every external effect arrives as an injected client, so these run
without a socket (ADR-0025 through ADR-0027; module-structure plan, PR 10).
The wizards that sequence these behind prompts are tested separately, in
``test_auth.py`` and ``test_setup_command.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from etsy_listings.core.application import credentials
from etsy_listings.core.clients.etsy import oauth
from etsy_listings.core.clients.etsy.callback import Callback
from etsy_listings.core.clients.etsy.oauth import OAuthError, TokenResponse
from etsy_listings.core.clients.etsy.tokens import TokenStore
from etsy_listings.core.clients.printify import PrintifyAuthError
from etsy_listings.core.clients.printify.fakes import FakePrintifyClient
from etsy_listings.core.clients.printify.models import Shop
from etsy_listings.core.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    EtsyAppKey,
)
from etsy_listings.core.workspace import layout

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

ALL_SCOPES = TokenResponse(
    access_token="12345678.access",
    refresh_token="12345678.refresh",
    expires_in=3600,
    scope=" ".join(oauth.SCOPES),
)


@pytest.fixture(autouse=True)
def _no_credentials_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (PRINTIFY_TOKEN_VAR, ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv(ANTHROPIC_KEY_VAR, raising=False)


def _env(root: Path) -> str:
    path = root / layout.ENV_FILE
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _token_store(root: Path) -> TokenStore:
    def refresh(_: str) -> TokenResponse:  # pragma: no cover - never refreshed here
        raise AssertionError("signing in does not refresh")

    return TokenStore(
        root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE, refresh=refresh, now=lambda: T0
    )


# ---------------------------------------------------------------- precedence


def test_a_credential_in_the_environment_wins_over_the_workspace_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / layout.ENV_FILE).write_text(f"{PRINTIFY_TOKEN_VAR}=from-file\n", encoding="utf-8")
    monkeypatch.setenv(PRINTIFY_TOKEN_VAR, "from-env")

    assert credentials.stored(tmp_path, PRINTIFY_TOKEN_VAR) == "from-env"


def test_the_workspace_file_answers_when_the_environment_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / layout.ENV_FILE).write_text(f"{PRINTIFY_TOKEN_VAR}=from-file\n", encoding="utf-8")
    monkeypatch.delenv(PRINTIFY_TOKEN_VAR, raising=False)

    assert credentials.stored(tmp_path, PRINTIFY_TOKEN_VAR) == "from-file"


def test_half_an_app_key_pair_is_reported_half_present(tmp_path: Path) -> None:
    (tmp_path / layout.ENV_FILE).write_text(f"{ETSY_KEYSTRING_VAR}=k\n", encoding="utf-8")

    assert credentials.stored_values(tmp_path, credentials.ETSY_APP_KEY) == ("k", None)


# ------------------------------------------------------------------- storage


def test_storing_a_pair_writes_both_halves_beside_what_is_there(tmp_path: Path) -> None:
    (tmp_path / layout.ENV_FILE).write_text("OTHER=kept\n", encoding="utf-8")

    credentials.store(tmp_path, credentials.ETSY_APP_KEY, ("k", "s"))

    env = _env(tmp_path)
    assert "OTHER=kept" in env
    assert f"{ETSY_KEYSTRING_VAR}=k" in env
    assert f"{ETSY_SHARED_SECRET_VAR}=s" in env


def test_a_blank_optional_credential_writes_nothing(tmp_path: Path) -> None:
    credentials.store(tmp_path, credentials.ANTHROPIC, ("",))

    assert not (tmp_path / layout.ENV_FILE).exists()


def test_a_blank_required_credential_is_refused_rather_than_stored(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=PRINTIFY_TOKEN_VAR):
        credentials.store(tmp_path, credentials.PRINTIFY, ("  ",))

    assert not (tmp_path / layout.ENV_FILE).exists()


# -------------------------------------------------------------- verification


def test_a_printify_token_is_proved_by_the_shops_it_reaches() -> None:
    shops = [Shop(id=1, title="A store", sales_channel="etsy")]
    seen: list[str] = []

    def client_for(token: str) -> FakePrintifyClient:
        seen.append(token)
        return FakePrintifyClient(shops)

    assert credentials.verify_printify_token("tok", client_for=client_for) == shops
    assert seen == ["tok"]


def test_a_rejected_printify_token_raises_and_stores_nothing(tmp_path: Path) -> None:
    with pytest.raises(PrintifyAuthError):
        credentials.verify_printify_token(
            "bad", client_for=lambda _: FakePrintifyClient(auth_fails=True)
        )

    assert not (tmp_path / layout.ENV_FILE).exists()


def test_an_etsy_app_key_is_proved_by_one_ping_carrying_both_halves() -> None:
    headers: list[str] = []

    class Transport:
        def __init__(self, app_key: EtsyAppKey) -> None:
            headers.append(app_key.header())

        def ping(self) -> int:
            return 4242

    application = credentials.verify_etsy_app_key(EtsyAppKey("k", "s"), transport_for=Transport)

    assert application == 4242
    assert headers == ["k:s"]


# -------------------------------------------------------------------- status


def test_an_empty_workspace_reports_every_required_credential_missing(tmp_path: Path) -> None:
    status = credentials.credential_status(tmp_path, tokens=_token_store(tmp_path), now=T0)

    assert set(status.missing) == {PRINTIFY_TOKEN_VAR, ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR}
    assert status.optional_missing == (ANTHROPIC_KEY_VAR,)
    assert not status.sign_in.present
    assert status.env_file == tmp_path / layout.ENV_FILE


def test_status_reads_the_stored_consent_without_refreshing_it(tmp_path: Path) -> None:
    store = _token_store(tmp_path)
    store.record(ALL_SCOPES)

    status = credentials.credential_status(tmp_path, tokens=store, now=T0 + timedelta(days=80))

    assert status.sign_in.user_id == 12345678
    assert status.sign_in.refresh_days == 10
    assert status.sign_in.renewal_due


def test_a_consent_with_time_left_is_not_due_for_renewal(tmp_path: Path) -> None:
    store = _token_store(tmp_path)
    store.record(ALL_SCOPES)

    assert not credentials.summarise(store.load(), now=T0).renewal_due
    assert not credentials.summarise(None, now=T0).renewal_due


# ------------------------------------------------------------- Etsy sign-in


def test_a_sign_in_asks_for_every_scope_at_the_fixed_callback() -> None:
    sign_in = credentials.begin_etsy_sign_in(EtsyAppKey("k", "s"))

    query = parse_qs(urlsplit(sign_in.url).query)
    assert query["client_id"] == ["k"]
    assert query["redirect_uri"] == [oauth.REDIRECT_URI]
    assert query["scope"] == [" ".join(oauth.SCOPES)]
    assert query["state"] == [sign_in.state]


class _OAuth:
    def __init__(self, response: TokenResponse) -> None:
        self.response = response
        self.exchanged: list[tuple[str, str]] = []

    def exchange(self, *, code: str, verifier: str) -> TokenResponse:
        self.exchanged.append((code, verifier))
        return self.response


def test_completing_a_sign_in_exchanges_the_code_and_persists_the_tokens(tmp_path: Path) -> None:
    sign_in = credentials.begin_etsy_sign_in(EtsyAppKey("k", "s"))
    client = _OAuth(ALL_SCOPES)
    store = _token_store(tmp_path)

    signed_in = credentials.complete_etsy_sign_in(
        sign_in, Callback(code="c0de", state=sign_in.state), oauth_client=client, tokens=store
    )

    assert client.exchanged == [("c0de", sign_in.pkce.verifier)]
    assert signed_in.tokens.user_id == 12345678
    assert signed_in.granted_every_scope
    assert store.load() == signed_in.tokens


def test_a_partial_grant_is_reported_rather_than_refused(tmp_path: Path) -> None:
    sign_in = credentials.begin_etsy_sign_in(EtsyAppKey("k", "s"))
    partial = TokenResponse(
        access_token="12345678.access",
        refresh_token="12345678.refresh",
        expires_in=3600,
        scope="listings_r",
    )

    signed_in = credentials.complete_etsy_sign_in(
        sign_in,
        Callback(code="c0de", state=sign_in.state),
        oauth_client=_OAuth(partial),
        tokens=_token_store(tmp_path),
    )

    assert not signed_in.granted_every_scope


def test_a_redirect_from_another_request_is_refused_before_any_exchange(tmp_path: Path) -> None:
    sign_in = credentials.begin_etsy_sign_in(EtsyAppKey("k", "s"))
    client = _OAuth(ALL_SCOPES)
    store = _token_store(tmp_path)

    with pytest.raises(OAuthError):
        credentials.complete_etsy_sign_in(
            sign_in, Callback(code="c0de", state="forged"), oauth_client=client, tokens=store
        )

    assert client.exchanged == []
    assert store.load() is None

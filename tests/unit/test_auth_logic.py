"""What `auth` reports, with no terminal and no network.

All of it is about credentials that already exist: which are missing, how much
life the Etsy consent has left, and whether that is worth saying out loud.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from etsy_listings.authcmd import logic
from etsy_listings.clients.etsy.oauth import TokenResponse
from etsy_listings.clients.etsy.tokens import StoredTokens
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    Secrets,
)

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

TOKENS = StoredTokens.from_response(
    TokenResponse(
        access_token="12345678.access",
        refresh_token="12345678.refresh",
        expires_in=3600,
        scope="listings_r listings_w shops_r",
    ),
    now=T0,
)


# ------------------------------------------------------------------ summary


def test_no_stored_tokens_reads_as_not_signed_in() -> None:
    summary = logic.summarise(None, now=T0)

    assert not summary.present
    assert "none stored" in summary.line()


def test_a_fresh_consent_reports_the_user_and_the_days_left() -> None:
    summary = logic.summarise(TOKENS, now=T0)

    assert summary.user_id == 12345678
    assert summary.access_valid
    assert summary.refresh_days == 90
    assert "12345678" in summary.line()


def test_an_expired_access_token_is_not_a_problem_worth_alarming_about() -> None:
    """It refreshes on the next use. Only the refresh token's death costs a
    browser trip, so only that one is worth a user's attention."""
    summary = logic.summarise(TOKENS, now=T0 + timedelta(hours=2))

    assert summary.present
    assert not summary.access_valid
    assert "refreshed on next use" in summary.line()


def test_an_expired_consent_reports_zero_days_rather_than_a_negative_number() -> None:
    summary = logic.summarise(TOKENS, now=T0 + timedelta(days=100))

    assert summary.refresh_days == 0


# ------------------------------------------------------------------ warning


def test_no_warning_while_there_is_plenty_of_time() -> None:
    assert logic.renewal_warning(logic.summarise(TOKENS, now=T0)) is None


def test_no_warning_when_there_is_nothing_stored() -> None:
    assert logic.renewal_warning(logic.summarise(None, now=T0)) is None


def test_the_last_fortnight_earns_a_warning_naming_the_command() -> None:
    summary = logic.summarise(TOKENS, now=T0 + timedelta(days=80))

    warning = logic.renewal_warning(summary)

    assert warning is not None
    assert "10 days" in warning
    assert "auth" in warning


# -------------------------------------------------------------- credentials


def _secrets(tmp_path: Path, **values: str) -> Secrets:
    return Secrets(env_file=tmp_path / ".env", **values)


def test_an_empty_workspace_is_missing_every_required_credential(tmp_path: Path) -> None:
    missing = logic.missing_credentials(_secrets(tmp_path))

    assert set(missing) == {PRINTIFY_TOKEN_VAR, ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR}


def test_half_an_etsy_key_pair_still_counts_as_missing(tmp_path: Path) -> None:
    """Both halves go into one header, so one of them is worth nothing."""
    missing = logic.missing_credentials(_secrets(tmp_path, etsy_keystring="k"))

    assert ETSY_SHARED_SECRET_VAR in missing
    assert ETSY_KEYSTRING_VAR not in missing


def test_a_complete_workspace_is_missing_nothing(tmp_path: Path) -> None:
    secrets = _secrets(
        tmp_path,
        printify_api_token="p",
        etsy_keystring="k",
        etsy_shared_secret="s",
    )

    assert logic.missing_credentials(secrets) == ()


def test_the_anthropic_key_is_optional_rather_than_missing(tmp_path: Path) -> None:
    """Nothing before Phase 4 asks for one, and reporting a workspace as
    incomplete for a feature it does not have yet teaches people to ignore the
    report."""
    secrets = _secrets(tmp_path, printify_api_token="p", etsy_keystring="k", etsy_shared_secret="s")

    assert logic.missing_credentials(secrets) == ()
    assert logic.optional_credentials(secrets) == (ANTHROPIC_KEY_VAR,)
    assert logic.optional_credentials(_secrets(tmp_path, anthropic_api_key="a")) == ()

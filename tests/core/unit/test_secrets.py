"""Credentials read from a workspace's `.env`, and what happens when one is
absent.

The subject here is the *message*, not the lookup. A missing credential that
surfaces as a bare `401` out of httpx tells a user nothing they can act on, so
every `require_*` names the variable, the file it belongs in, and where the
value comes from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.config.secrets import (
    BACKUP_PASSWORD_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
    MissingCredentialError,
    Secrets,
)


def _env(tmp_path: Path, content: str) -> Secrets:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    return Secrets.load(path)


@pytest.fixture(autouse=True)
def _no_ambient_etsy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR):
        monkeypatch.delenv(name, raising=False)


def test_a_missing_file_is_not_an_error_only_an_absence(tmp_path: Path) -> None:
    """Every phase before the one that needs a credential must still run."""
    secrets = Secrets.load(tmp_path / ".env")

    assert secrets.etsy_keystring is None
    assert secrets.etsy_shared_secret is None


def test_both_halves_of_the_etsy_key_are_read(tmp_path: Path) -> None:
    secrets = _env(tmp_path, f"{ETSY_KEYSTRING_VAR}=abc123\n{ETSY_SHARED_SECRET_VAR}=s3cret\n")

    key = secrets.require_etsy_app_key()

    assert key.keystring == "abc123"
    assert key.shared_secret == "s3cret"


def test_the_header_joins_the_pair_with_a_colon(tmp_path: Path) -> None:
    """`x-api-key` carries both halves, and this is the only place the colon
    is spelled -- a request that dropped the shared secret would be rejected
    by Etsy with no hint as to which half was wrong."""
    secrets = _env(tmp_path, f"{ETSY_KEYSTRING_VAR}=abc123\n{ETSY_SHARED_SECRET_VAR}=s3cret\n")

    assert secrets.require_etsy_app_key().header() == "abc123:s3cret"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("", ETSY_KEYSTRING_VAR),
        (f"{ETSY_KEYSTRING_VAR}=abc123\n", ETSY_SHARED_SECRET_VAR),
        (f"{ETSY_SHARED_SECRET_VAR}=s3cret\n", ETSY_KEYSTRING_VAR),
    ],
)
def test_a_missing_half_is_reported_by_name(tmp_path: Path, content: str, expected: str) -> None:
    """One variable at a time: "the Etsy app key is missing" sends someone who
    pasted the keystring back to a page where the keystring is plainly there,
    and the shared secret is the half hidden behind a visibility toggle."""
    with pytest.raises(MissingCredentialError) as caught:
        _env(tmp_path, content).require_etsy_app_key()

    assert caught.value.variable == expected
    assert str(tmp_path / ".env") in str(caught.value)
    assert "auth" in str(caught.value)


def test_the_process_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What makes a one-off `ETSY_KEYSTRING=... etsy-listings ...` work."""
    monkeypatch.setenv(ETSY_KEYSTRING_VAR, "from-the-shell")

    secrets = _env(tmp_path, f"{ETSY_KEYSTRING_VAR}=from-the-file\n{ETSY_SHARED_SECRET_VAR}=s\n")

    assert secrets.require_etsy_app_key().keystring == "from-the-shell"


def test_secrets_read_the_workspace_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PRINTIFY_API_TOKEN", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("PRINTIFY_API_TOKEN=from-dotenv\n", encoding="utf-8")
    secrets = Secrets.load(env_file)
    assert secrets.require_printify_api_token() == "from-dotenv"


def test_missing_token_names_the_file_it_should_be_in(tmp_path: Path, monkeypatch) -> None:
    """Printify's catalog is not public: the message has to name the token,
    the `.env` it belongs in and where to get one with the right scope."""
    monkeypatch.delenv(PRINTIFY_TOKEN_VAR, raising=False)
    secrets = Secrets.load(tmp_path / ".env")
    with pytest.raises(MissingCredentialError) as exc_info:
        secrets.require_printify_api_token()
    message = str(exc_info.value)
    assert exc_info.value.variable == PRINTIFY_TOKEN_VAR
    assert message.startswith(f"{PRINTIFY_TOKEN_VAR} is not set")
    assert f"Put it in {tmp_path / '.env'} as `{PRINTIFY_TOKEN_VAR}=...`" in message
    assert "printify.com/app/account/connections" in message
    assert "`catalog.read` scope" in message


def test_the_backup_password_is_read_from_the_workspace_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)

    secrets = _env(tmp_path, f"{BACKUP_PASSWORD_VAR}=correct horse battery\n")

    assert secrets.backup_password == "correct horse battery"


def test_a_backup_password_holding_a_dollar_brace_is_read_literally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.setenv("HOME", "/somewhere")

    secrets = _env(tmp_path, f"{BACKUP_PASSWORD_VAR}=pa${{HOME}}ss\n")

    assert secrets.backup_password == "pa${HOME}ss"


def test_a_missing_backup_password_names_the_variable_and_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)

    with pytest.raises(MissingCredentialError) as caught:
        _env(tmp_path, "").require_backup_password()

    assert caught.value.variable == BACKUP_PASSWORD_VAR
    assert str(tmp_path / ".env") in str(caught.value)
    assert "backup init" in str(caught.value)


def test_the_backup_password_stays_out_of_the_secrets_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``Secrets`` that reaches a log line or a traceback's locals must not
    carry the only key to every backup (workspace-backup plan, PR 2)."""
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)

    secrets = _env(tmp_path, f"{BACKUP_PASSWORD_VAR}=correct horse battery\n")

    assert "correct horse battery" not in repr(secrets)

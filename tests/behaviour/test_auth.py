"""`auth`, driven end to end with scripted answers and fake backends.

No terminal, no browser, no socket: prompts are answered by matching on the
question's text, and everything that would leave the process arrives through
:class:`Backends`. What is asserted is what the command leaves on disk -- the
`.env`, the `.gitignore` and the token file that every later command reads --
rather than the order the questions were asked in.

The one ordering that *is* asserted is the `.gitignore`: `auth` may be the
first thing ever written into a directory, and a `.env` that lands before the
ignore rule is a secret inside somebody's repository (PRD 49).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from etsy_listings.authcmd.interactive import Backends, run_auth
from etsy_listings.clients.etsy.callback import Callback
from etsy_listings.clients.etsy.oauth import OAuthError, TokenResponse
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.clients.printify.models import Shop
from etsy_listings.config.secrets import (
    ANTHROPIC_KEY_VAR,
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
)
from etsy_listings.workspace import layout

from tests.support import scripted

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

ANSWERS = {
    "Printify API token": "printify-token-abc",
    "Etsy keystring": "keystring-123",
    "Etsy shared secret": "shared-secret-456",
    "Anthropic API key": "",
    "Sign in to Etsy again": False,
}

TOKEN_RESPONSE = TokenResponse(
    access_token="12345678.access",
    refresh_token="12345678.refresh",
    expires_in=3600,
    scope="listings_r listings_w shops_r",
)


class FakeEtsy:
    """Etsy's two authenticated surfaces, and a record of what reached them."""

    def __init__(self, *, exchange: Any = TOKEN_RESPONSE, ping: int = 4242) -> None:
        self.exchange_result = exchange
        self.ping_result = ping
        self.pinged_with: list[str] = []
        self.exchanged: list[dict[str, str]] = []
        self.browsed: list[str] = []

    # The transport `auth` pings with, and the OAuth client it exchanges with.
    def transport(self, app_key: Any) -> Any:
        fake = self

        class _Transport:
            def ping(self) -> int:
                fake.pinged_with.append(app_key.header())
                return fake.ping_result

        return _Transport()

    def oauth_client(self, keystring: str) -> Any:
        fake = self

        class _Client:
            def exchange(self, *, code: str, verifier: str) -> TokenResponse:
                fake.exchanged.append({"code": code, "verifier": verifier})
                if isinstance(fake.exchange_result, Exception):
                    raise fake.exchange_result
                return fake.exchange_result

            def refresh(self, refresh_token: str) -> TokenResponse:  # pragma: no cover
                raise AssertionError("`auth` signs in; it does not refresh")

        return _Client()

    def open_browser(self, url: str) -> bool:
        self.browsed.append(url)
        return True

    def redirect(self, *, state: str | None = None, code: str = "c0de") -> Callback:
        """The redirect Etsy would send, echoing back the state we sent.

        Taken from the URL that was actually opened rather than fixed, so the
        `state` check is exercised by the happy path instead of being trusted.
        """
        if state is None:
            query = parse_qs(urlsplit(self.browsed[-1]).query)
            state = query["state"][0]
        return Callback(code=code, state=state)


def backends(etsy: FakeEtsy, printify: FakePrintifyClient, **overrides: Any) -> Backends:
    defaults: dict[str, Any] = {
        "printify_client": lambda _token: printify,
        "etsy_transport": etsy.transport,
        "oauth_client": etsy.oauth_client,
        "wait_for_redirect": lambda: etsy.redirect(),
        "open_browser": etsy.open_browser,
        "now": lambda: T0,
    }
    return Backends(**{**defaults, **overrides})


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer machine has some of these exported. These tests decide for
    themselves what already exists."""
    for name in (PRINTIFY_TOKEN_VAR, ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR, ANTHROPIC_KEY_VAR):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def etsy() -> FakeEtsy:
    return FakeEtsy()


@pytest.fixture
def printify() -> FakePrintifyClient:
    return FakePrintifyClient([Shop(id=1, title="A store", sales_channel="etsy")])


def env_values(root: Path) -> dict[str, str]:
    text = (root / layout.ENV_FILE).read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def tokens_document(root: Path) -> dict[str, Any]:
    path = root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------- the full run


def test_a_first_run_stores_every_credential_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    scripted.install(monkeypatch, dict(ANSWERS, **{"Anthropic API key": "sk-ant-123"}))

    run_auth(tmp_path, backends=backends(etsy, printify))

    assert env_values(tmp_path) == {
        PRINTIFY_TOKEN_VAR: "printify-token-abc",
        ETSY_KEYSTRING_VAR: "keystring-123",
        ETSY_SHARED_SECRET_VAR: "shared-secret-456",
        ANTHROPIC_KEY_VAR: "sk-ant-123",
    }


def test_the_gitignore_is_written_before_any_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    """`auth` runs before `setup`, so it may be the first thing written into a
    directory some repository is already tracking."""
    written: list[str] = []
    real_write = Path.write_text

    def spy(self: Path, *args: Any, **kwargs: Any) -> int:
        written.append(self.name)
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)
    scripted.install(monkeypatch, ANSWERS)

    run_auth(tmp_path, backends=backends(etsy, printify))

    assert written.index(".gitignore") < written.index(layout.ENV_FILE)
    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert layout.ENV_FILE in ignored
    assert layout.AUTH_DIR in ignored


def test_the_etsy_key_pair_is_pinged_before_it_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    """A keystring typo surfaces here rather than as an Etsy error page in the
    middle of the consent screen."""
    scripted.install(monkeypatch, ANSWERS)

    run_auth(tmp_path, backends=backends(etsy, printify))

    assert etsy.pinged_with == ["keystring-123:shared-secret-456"]


def test_the_browser_is_sent_the_authorize_url_and_the_code_is_exchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    scripted.install(monkeypatch, ANSWERS)

    run_auth(tmp_path, backends=backends(etsy, printify))

    query = parse_qs(urlsplit(etsy.browsed[0]).query)
    assert query["client_id"] == ["keystring-123"]
    assert query["code_challenge_method"] == ["S256"]
    assert etsy.exchanged == [{"code": "c0de", "verifier": etsy.exchanged[0]["verifier"]}]
    # The verifier sent is the pre-image of the challenge shown to the browser.
    assert len(etsy.exchanged[0]["verifier"]) >= 43


def test_the_tokens_land_in_the_auth_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    scripted.install(monkeypatch, ANSWERS)

    run_auth(tmp_path, backends=backends(etsy, printify))

    document = tokens_document(tmp_path)
    assert document["access_token"] == "12345678.access"
    assert document["refresh_token"] == "12345678.refresh"
    assert document["user_id"] == 12345678


# ------------------------------------------------------------------ re-runs


def test_a_credential_already_present_is_not_asked_for_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    """`auth` fills gaps. Re-running it must not turn an existing credential
    into a question whose blank answer would overwrite it."""
    (tmp_path / layout.ENV_FILE).write_text(
        f"{PRINTIFY_TOKEN_VAR}=already-here\n", encoding="utf-8"
    )
    script = scripted.install(monkeypatch, ANSWERS)

    run_auth(tmp_path, backends=backends(etsy, printify))

    assert not any("Printify API token" in question for question in script.asked)
    assert env_values(tmp_path)[PRINTIFY_TOKEN_VAR] == "already-here"


def test_an_existing_sign_in_is_left_alone_unless_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    """Re-authorising costs a browser, a password and a consent screen. A
    wizard that spends those on every re-run teaches people not to re-run it."""
    scripted.install(monkeypatch, ANSWERS)
    run_auth(tmp_path, backends=backends(etsy, printify))
    first = tokens_document(tmp_path)

    second_etsy = FakeEtsy()
    scripted.install(monkeypatch, ANSWERS)
    run_auth(tmp_path, backends=backends(second_etsy, printify))

    assert second_etsy.browsed == []
    assert tokens_document(tmp_path) == first


def test_saying_yes_to_signing_in_again_runs_the_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    scripted.install(monkeypatch, ANSWERS)
    run_auth(tmp_path, backends=backends(etsy, printify))

    again = FakeEtsy(
        exchange=TokenResponse(
            access_token="12345678.newer",
            refresh_token="12345678.newer-refresh",
            expires_in=3600,
            scope="listings_r listings_w shops_r",
        )
    )
    scripted.install(monkeypatch, dict(ANSWERS, **{"Sign in to Etsy again": True}))
    run_auth(tmp_path, backends=backends(again, printify))

    assert again.browsed != []
    assert tokens_document(tmp_path)["access_token"] == "12345678.newer"


# ---------------------------------------------------------------- refusals


def test_a_rejected_printify_token_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy
) -> None:
    import typer

    scripted.install(monkeypatch, ANSWERS)
    rejecting = FakePrintifyClient(auth_fails=True)

    with pytest.raises(typer.Exit):
        run_auth(tmp_path, backends=backends(etsy, rejecting))

    assert not (tmp_path / layout.ENV_FILE).is_file()


def test_a_redirect_carrying_the_wrong_state_stores_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, etsy: FakeEtsy, printify: FakePrintifyClient
) -> None:
    """The CSRF case `state` exists to catch: the redirect belongs to a flow
    this process did not start, so nothing about it is trusted."""
    scripted.install(monkeypatch, ANSWERS)
    wrong = backends(etsy, printify, wait_for_redirect=lambda: Callback(code="c", state="theirs"))

    with pytest.raises(OAuthError) as caught:
        run_auth(tmp_path, backends=wrong)

    assert caught.value.error == "state_mismatch"
    assert not (tmp_path / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE).exists()
    assert etsy.exchanged == []


def test_a_used_authorization_code_stores_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, printify: FakePrintifyClient
) -> None:
    scripted.install(monkeypatch, ANSWERS)
    refusing = FakeEtsy(exchange=OAuthError("invalid_grant", "code has been used previously"))

    with pytest.raises(OAuthError):
        run_auth(tmp_path, backends=backends(refusing, printify))

    assert not (tmp_path / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE).exists()


# ------------------------------------------------------------------- --check


def test_check_reports_without_writing_anything(
    tmp_path: Path, etsy: FakeEtsy, printify: FakePrintifyClient, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "Am I still signed in?" should never be a question you have to risk
    changing something to ask."""
    run_auth(tmp_path, backends=backends(etsy, printify), check=True)

    captured = capsys.readouterr().out
    assert "none stored" in captured
    assert PRINTIFY_TOKEN_VAR in captured
    assert list(tmp_path.iterdir()) == []


def test_check_reports_the_stored_consent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    etsy: FakeEtsy,
    printify: FakePrintifyClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scripted.install(monkeypatch, ANSWERS)
    run_auth(tmp_path, backends=backends(etsy, printify))
    capsys.readouterr()

    run_auth(tmp_path, backends=backends(etsy, printify), check=True)

    captured = capsys.readouterr().out
    assert "user 12345678" in captured
    assert "90 more days" in captured
    assert "All required credentials present" in captured

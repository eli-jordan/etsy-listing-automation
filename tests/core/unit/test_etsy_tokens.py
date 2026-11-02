"""The token file, and the rotation rules that make it worth having.

The clock is injected everywhere, so "the access token expired" and "the
consent is 89 days old" are ordinary assertions rather than waits. The refresh
call is a stub for the same reason: what is under test here is *what gets
written and when*, which is the half that loses a credential when it is wrong.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.clients.etsy import tokens
from etsy_listings.core.clients.etsy.oauth import OAuthError, TokenResponse
from etsy_listings.core.clients.etsy.tokens import (
    REFRESH_TOKEN_LIFETIME,
    EtsyAuthError,
    EtsyRefreshBusyError,
    StoredTokens,
    TokenStore,
)

from tests.support.etsy_grants import RotatingGrant
from tests.support.gates import STAYS_OUT, Gate, workers

T0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def response(
    *, access: str = "12345678.access", refresh: str = "12345678.refresh"
) -> TokenResponse:
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=3600,
        scope="listings_r listings_w shops_r",
    )


def stored(*, now: datetime = T0, **overrides: object) -> StoredTokens:
    base = StoredTokens.from_response(response(), now=now)
    return StoredTokens(**{**base.__dict__, **overrides})


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, at: datetime = T0) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, delta: timedelta) -> None:
        self.at += delta


# ------------------------------------------------------------ the document


def test_a_stored_pair_survives_a_round_trip(tmp_path: Path) -> None:
    tokens = stored()

    assert StoredTokens.parse(tokens.to_document()) == tokens


def test_the_document_records_absolute_instants_a_human_can_read() -> None:
    """`expires_in` seconds are meaningless once the process that received
    them is gone, and this file outlives it."""
    document = stored().to_document()

    assert document["expires_at"] == (T0 + timedelta(seconds=3600)).isoformat()
    assert document["refresh_expires_at"] == (T0 + REFRESH_TOKEN_LIFETIME).isoformat()


@pytest.mark.parametrize(
    "document",
    ["not an object", {}, {"access_token": "a"}, {**stored().to_document(), "expires_at": "soon"}],
)
def test_a_document_that_will_not_decode_reads_as_absent(document: object) -> None:
    """The same answer the lockfile gives, for the same reason: a credential
    file we cannot read is one we cannot prove anything about."""
    assert StoredTokens.parse(document) is None


def test_freshness_leaves_a_margin_before_the_real_expiry() -> None:
    tokens = stored()

    assert tokens.is_fresh(T0)
    assert not tokens.is_fresh(T0 + timedelta(minutes=57))


# ------------------------------------------------------------- reading back


def test_a_missing_file_reads_as_no_tokens(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "absent.json", refresh=_never)

    assert store.load() is None


def test_unreadable_json_reads_as_no_tokens(tmp_path: Path) -> None:
    path = tmp_path / "etsy-tokens.json"
    path.write_text("{ not json", encoding="utf-8")

    assert TokenStore(path, refresh=_never).load() is None


def test_a_token_is_demanded_only_where_one_is_needed(tmp_path: Path) -> None:
    """Building a store must not require credentials -- `plan` builds clients
    it may never call. Asking for a token is what fails."""
    store = TokenStore(tmp_path / "absent.json", refresh=_never)

    with pytest.raises(EtsyAuthError) as caught:
        store.access_token()
    assert "auth" in str(caught.value)


# ---------------------------------------------------------------- rotation


def test_a_fresh_token_is_returned_without_a_refresh(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "t.json", refresh=_never, now=Clock())
    store.record(response())

    assert store.access_token() == "12345678.access"


def test_an_expiring_token_is_refreshed_and_the_new_pair_written(tmp_path: Path) -> None:
    clock = Clock()
    calls: list[str] = []

    def refresh(token: str) -> TokenResponse:
        calls.append(token)
        return response(access="12345678.new-access", refresh="12345678.new-refresh")

    path = tmp_path / "t.json"
    store = TokenStore(path, refresh=refresh, now=clock)
    store.record(response())
    clock.advance(timedelta(minutes=58))

    assert store.access_token() == "12345678.new-access"
    assert calls == ["12345678.refresh"]
    # Rotation is only useful if it is recorded: the old refresh token is
    # spent, and a run that used the new access token without writing the new
    # refresh token would have no way back.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["refresh_token"] == "12345678.new-refresh"
    assert on_disk["expires_at"] == (clock.at + timedelta(seconds=3600)).isoformat()


def test_rotation_restarts_the_ninety_day_clock_optimistically(tmp_path: Path) -> None:
    """Etsy does not document whether a refresh extends the refresh token's
    life, so the stored date is a guess -- and `invalid_grant` is what
    actually settles it."""
    clock = Clock()
    store = TokenStore(tmp_path / "t.json", refresh=lambda _: response(), now=clock)
    store.record(response())
    clock.advance(timedelta(days=30))

    store.access_token()

    tokens = store.load()
    assert tokens is not None
    assert tokens.refresh_expires_at == clock.at + REFRESH_TOKEN_LIFETIME


def test_a_dead_refresh_token_asks_the_user_to_sign_in_again(tmp_path: Path) -> None:
    def refresh(_: str) -> TokenResponse:
        raise OAuthError("invalid_grant", "token expired")

    clock = Clock()
    store = TokenStore(tmp_path / "t.json", refresh=refresh, now=clock)
    store.record(response())
    clock.advance(timedelta(days=91))

    with pytest.raises(EtsyAuthError) as caught:
        store.access_token()
    assert "auth" in str(caught.value)


def test_a_non_grant_failure_is_not_reported_as_a_dead_consent(tmp_path: Path) -> None:
    """A 500 from the token endpoint is not a reason to send someone to a
    browser."""

    def refresh(_: str) -> TokenResponse:
        raise OAuthError("server_error", "try later")

    clock = Clock()
    store = TokenStore(tmp_path / "t.json", refresh=refresh, now=clock)
    store.record(response())
    clock.advance(timedelta(minutes=58))

    with pytest.raises(OAuthError):
        store.access_token()


def test_a_rotation_by_another_process_is_read_rather_than_reported(tmp_path: Path) -> None:
    """Two runs at once: the first rotates, the second's refresh token is
    already spent. `invalid_grant` there means "you are holding yesterday's
    token", not "the user must sign in" -- so the file is re-read first."""
    clock = Clock()
    path = tmp_path / "t.json"

    def refresh(_: str) -> TokenResponse:
        # Stand in for the other process: it rotated while we were asking.
        other = TokenStore(path, refresh=_never, now=clock)
        other.save(
            StoredTokens.from_response(
                response(access="12345678.theirs", refresh="12345678.their-refresh"),
                now=clock.at,
            )
        )
        raise OAuthError("invalid_grant", "already used")

    store = TokenStore(path, refresh=refresh, now=clock)
    store.record(response())
    clock.advance(timedelta(minutes=58))

    assert store.access_token() == "12345678.theirs"


def expired_pair(path: Path, clock: Clock, refresh_token: str = "12345678.refresh") -> None:
    TokenStore(path, refresh=_never, now=clock).record(response(refresh=refresh_token))
    clock.advance(timedelta(minutes=58))


def test_two_stores_for_one_file_rotate_its_grant_once(tmp_path: Path) -> None:
    """Admin audit I1: the Admin page's connection and lookup requests each
    build a store for the same token file. Holding the first rotation before
    it is saved, the second store must wait and use the new pair rather than
    spend the old refresh token again and report a withdrawn consent."""
    clock = Clock()
    path = tmp_path / "t.json"
    expired_pair(path, clock)
    held = Gate("the first rotation")
    grant = RotatingGrant("12345678.refresh", hold=held)
    first = TokenStore(path, refresh=grant.refresh, now=clock)
    second = TokenStore(path, refresh=grant.refresh, now=clock)

    with workers(held) as start:
        winner = start("first store", first.access_token)
        held.wait_entered()
        loser = start("second store", second.access_token)
        loser.thread.join(STAYS_OUT)
        held.release()
        tokens_used = {winner.outcome(), loser.outcome()}

    assert tokens_used == {"12345678.access-1"}
    assert (grant.rotations, grant.refused) == (1, 0)
    assert TokenStore(path, refresh=_never).load().refresh_token == grant.current


def test_a_revoked_grant_still_asks_every_store_to_sign_in(tmp_path: Path) -> None:
    clock = Clock()
    path = tmp_path / "t.json"
    expired_pair(path, clock)
    grant = RotatingGrant("12345678.refresh")
    grant.revoke()

    for store in (TokenStore(path, refresh=grant.refresh, now=clock) for _ in range(2)):
        with pytest.raises(EtsyAuthError, match="consent was withdrawn"):
            store.access_token()

    assert grant.rotations == 0


def test_a_rotation_for_another_token_file_does_not_wait(tmp_path: Path) -> None:
    """Serialised per token file, not process-wide: one workspace's slow
    refresh never holds up another's."""
    clock = Clock()
    held = Gate("the first workspace's rotation")
    paths = [tmp_path / "a" / "t.json", tmp_path / "b" / "t.json"]
    for path in paths:
        expired_pair(path, clock)
    slow = RotatingGrant("12345678.refresh", hold=held)
    other = RotatingGrant("12345678.refresh")

    with workers(held) as start:
        start("first workspace", TokenStore(paths[0], refresh=slow.refresh, now=clock).access_token)
        held.wait_entered()
        assert TokenStore(paths[1], refresh=other.refresh, now=clock).access_token() == (
            "12345678.access-1"
        )
        held.release()


def test_a_rotation_held_past_the_wait_is_a_retryable_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wedged refresh never hangs every other Etsy request: the waiter
    gives up with an error that names no token and asks for no sign-in."""
    monkeypatch.setattr(tokens, "ROTATION_WAIT_SECONDS", STAYS_OUT)
    clock = Clock()
    path = tmp_path / "t.json"
    expired_pair(path, clock)
    held = Gate("the wedged rotation")
    grant = RotatingGrant("12345678.refresh", hold=held)

    with workers(held) as start:
        start("wedged store", TokenStore(path, refresh=grant.refresh, now=clock).access_token)
        held.wait_entered()
        with pytest.raises(EtsyRefreshBusyError) as refused:
            TokenStore(path, refresh=grant.refresh, now=clock).access_token()
        held.release()

    message = str(refused.value)
    assert "still refreshing" in message
    assert "12345678." not in message
    assert "sign in" not in message
    assert grant.rotations == 1


# ------------------------------------------------------------------- saving


def test_saving_creates_the_auth_directory(tmp_path: Path) -> None:
    path = tmp_path / ".auth" / "etsy-tokens.json"

    TokenStore(path, refresh=_never).save(stored())

    assert path.is_file()


def test_saving_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """The write is atomic -- a temp file plus `os.replace` -- and the temp
    file is an implementation detail that must not outlive the call."""
    path = tmp_path / "t.json"

    TokenStore(path, refresh=_never).save(stored())

    assert [p.name for p in tmp_path.iterdir()] == ["t.json"]


def _never(_: str) -> TokenResponse:
    raise AssertionError("this test should not have refreshed")

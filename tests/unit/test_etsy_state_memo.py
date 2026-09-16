"""`ui/api/etsystate`'s memo: how often the listings UI is allowed to ask Etsy
which of its listings are published.

The memo is the reason the status badge can be resolved on every read.
``GET /api/listings/{name}`` is also what every autosave PATCH answers with,
so without it a keystroke burst in the editor would be a round trip apiece.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.tokens import EtsyAuthError
from etsy_listings.ui.api import etsystate


class Counting(FakeEtsyListingClient):
    def __init__(self, states: dict[int, str]) -> None:
        super().__init__()
        for listing_id, state in states.items():
            self.seed_listing(listing_id, state=state)
        self.calls = 0

    def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
        self.calls += 1
        return super().listing_states(listing_ids)


@pytest.fixture(autouse=True)
def _clean() -> None:
    etsystate.forget()


def install(monkeypatch: pytest.MonkeyPatch, client: object | None) -> None:
    monkeypatch.setattr(etsystate.connections, "etsy_listing_client", lambda _root: client)


ROOT = Path("/workspace")


def test_asks_once_and_answers_the_rest_from_the_memo(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Counting({111: "active", 222: "draft"})
    install(monkeypatch, fake)

    first = etsystate.live_listing_ids(ROOT, [111, 222], now=lambda: 0.0)
    second = etsystate.live_listing_ids(ROOT, [111, 222], now=lambda: 1.0)

    assert first == second == {111}
    assert fake.calls == 1


def test_re_asks_once_the_memo_has_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """A listing published in another tab is badged `deployed` for at most
    this long, which is the whole cost of the memo."""
    fake = Counting({111: "draft"})
    install(monkeypatch, fake)

    assert etsystate.live_listing_ids(ROOT, [111], now=lambda: 0.0) == set()
    fake.seed_listing(111, state="active")
    later = etsystate.TTL_SECONDS + 1

    assert etsystate.live_listing_ids(ROOT, [111], now=lambda: later) == {111}
    assert fake.calls == 2


def test_only_the_ids_it_has_no_answer_for_are_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Counting({111: "active", 222: "active"})
    install(monkeypatch, fake)
    asked: list[list[int]] = []
    original = fake.listing_states

    def record(listing_ids: Sequence[int]) -> dict[int, str]:
        asked.append(list(listing_ids))
        return original(listing_ids)

    monkeypatch.setattr(fake, "listing_states", record)

    etsystate.live_listing_ids(ROOT, [111], now=lambda: 0.0)
    etsystate.live_listing_ids(ROOT, [111, 222], now=lambda: 1.0)

    assert asked == [[111], [222]]


def test_an_id_etsy_never_answered_for_is_remembered_as_not_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listing deleted on Etsy must not re-ask every time the table is
    drawn -- "no answer" is an answer worth keeping for the TTL."""
    fake = Counting({})
    install(monkeypatch, fake)

    assert etsystate.live_listing_ids(ROOT, [999], now=lambda: 0.0) == set()
    assert etsystate.live_listing_ids(ROOT, [999], now=lambda: 1.0) == set()
    assert fake.calls == 1


def test_no_ids_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Counting({})
    install(monkeypatch, fake)

    assert etsystate.live_listing_ids(ROOT, [], now=lambda: 0.0) == set()
    assert fake.calls == 0


def test_a_workspace_with_no_etsy_credentials_reports_nothing_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary state well short of Phase 3: the listings page must still
    open, with every listing reported as not-live."""
    install(monkeypatch, None)

    assert etsystate.live_listing_ids(ROOT, [111], now=lambda: 0.0) == set()


def test_a_sign_in_that_has_expired_is_silence_not_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Expired(FakeEtsyListingClient):
        def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
            raise EtsyAuthError("No Etsy tokens in .auth/etsy-tokens.json.")

    install(monkeypatch, Expired())

    assert etsystate.live_listing_ids(ROOT, [111], now=lambda: 0.0) == set()

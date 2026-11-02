"""`server/api/etsystate`'s memo: how often the listings UI is allowed to ask Etsy
which of its listings are published.

The memo is the reason the status badge can be resolved on every read.
``GET /api/listings/{name}`` is also what every autosave PATCH answers with,
so without it a keystroke burst in the editor would be a round trip apiece.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.clients.etsy.tokens import EtsyAuthError, EtsyRefreshBusyError
from etsy_listings.core.config.secrets import MissingCredentialError
from etsy_listings.server.api import etsystate


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


ROOT = Path("/workspace")


def live(client: EtsyListingClient, listing_ids: list[int], at: float) -> set[int]:
    """Which of ``listing_ids`` the memo reports live at ``at``, asking ``client``."""
    return etsystate.live_listing_ids(
        ROOT, listing_ids, client_for=lambda _root: client, now=lambda: at
    )


def test_asks_once_and_answers_the_rest_from_the_memo() -> None:
    fake = Counting({111: "active", 222: "draft"})

    first = live(fake, [111, 222], at=0.0)
    second = live(fake, [111, 222], at=1.0)

    assert first == second == {111}
    assert fake.calls == 1


def test_re_asks_once_the_memo_has_expired() -> None:
    """A listing published in another tab is badged `deployed` for at most
    this long, which is the whole cost of the memo."""
    fake = Counting({111: "draft"})

    assert live(fake, [111], at=0.0) == set()
    fake.seed_listing(111, state="active")
    later = etsystate.TTL_SECONDS + 1

    assert live(fake, [111], at=later) == {111}
    assert fake.calls == 2


def test_only_the_ids_it_has_no_answer_for_are_fetched() -> None:
    asked: list[list[int]] = []

    class Recording(Counting):
        def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
            asked.append(list(listing_ids))
            return super().listing_states(listing_ids)

    fake = Recording({111: "active", 222: "active"})

    live(fake, [111], at=0.0)
    live(fake, [111, 222], at=1.0)

    assert asked == [[111], [222]]


def test_an_id_etsy_never_answered_for_is_remembered_as_not_live() -> None:
    """A listing deleted on Etsy must not re-ask every time the table is
    drawn -- "no answer" is an answer worth keeping for the TTL."""
    fake = Counting({})

    assert live(fake, [999], at=0.0) == set()
    assert live(fake, [999], at=1.0) == set()
    assert fake.calls == 1


def test_no_ids_asks_nothing() -> None:
    fake = Counting({})

    assert live(fake, [], at=0.0) == set()
    assert fake.calls == 0


@pytest.mark.parametrize(
    "failure",
    [
        MissingCredentialError("ETSY_KEYSTRING", ROOT / ".env", "read Etsy", "Run `auth etsy`."),
        EtsyAuthError("No Etsy tokens."),
        EtsyRefreshBusyError("Refresh still running. Try again shortly."),
    ],
    ids=["no-credentials", "signed-out", "refresh-busy"],
)
def test_an_etsy_read_failure_is_silence_not_a_500(failure: Exception) -> None:
    """A workspace with no Etsy credentials is an ordinary state well short
    of Phase 3: the listings page must still open, with every listing
    reported as not-live."""

    class Failing(FakeEtsyListingClient):
        def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
            raise failure

    assert live(Failing(), [111], at=0.0) == set()

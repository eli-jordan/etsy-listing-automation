"""Contract layer for the shop reads `setup` makes: paths, envelopes, and the
one response shape Etsy documents differently from how it behaves.

All four calls are unscoped -- the app key pair is enough -- which is what
lets `setup` resolve every id in `shop.yaml` without a browser sign-in
(PRD 49). Payloads are transcribed from Etsy's API reference; the `-m e2e`
layer is what re-takes them against the live API.
"""

from __future__ import annotations

import httpx
import pytest

from etsy_listings.clients.etsy.shops import HttpEtsyShopClient
from etsy_listings.clients.etsy.transport import EtsyApiError

from tests.support.http import etsy_transport

SHOP = {
    "shop_id": 12345678,
    "user_id": 87654321,
    "shop_name": "TakeAHikeTees",
    "title": "Trail-worn tees",
    "currency_code": "NOK",
    "is_vacation": False,
    "url": "https://www.etsy.com/shop/TakeAHikeTees",
}


def _client(handler) -> HttpEtsyShopClient:  # noqa: ANN001 - a test handler
    return HttpEtsyShopClient(etsy_transport(handler))


# ---------------------------------------------------------------- find_shops


def test_a_search_sends_the_name_as_a_query_parameter() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["name"] = request.url.params["shop_name"]
        return httpx.Response(200, json={"count": 1, "results": [SHOP]})

    found = _client(handler).find_shops("TakeAHikeTees")

    assert seen == {"path": "/v3/application/shops", "name": "TakeAHikeTees"}
    assert [shop.shop_id for shop in found] == [12345678]
    assert found[0].currency_code == "NOK"


def test_a_search_with_no_matches_is_an_empty_list_not_an_error() -> None:
    handler = lambda _: httpx.Response(200, json={"count": 0, "results": []})  # noqa: E731

    assert _client(handler).find_shops("nothing here") == []


def test_the_forty_odd_fields_we_do_not_model_are_ignored() -> None:
    """Etsy's Shop carries forty-seven fields. Modelling all of them would
    turn a field Etsy renames into a validation error in a workspace that
    never touched it."""
    handler = lambda _: httpx.Response(  # noqa: E731
        200, json={"count": 1, "results": [{**SHOP, "a_field_added_next_year": True}]}
    )

    assert _client(handler).find_shops("TakeAHikeTees")[0].shop_name == "TakeAHikeTees"


# ------------------------------------------------------------ shop_by_owner


def test_the_owner_lookup_reads_the_single_shop_it_returns() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/application/users/87654321/shops"
        return httpx.Response(200, json=SHOP)

    shop = _client(handler).shop_by_owner(87654321)

    assert shop is not None
    assert shop.shop_id == 12345678


def test_the_owner_lookup_also_reads_a_results_envelope() -> None:
    """Documented as a single Shop; the sibling search returns `results`.
    Tolerating both costs one line and removes a whole class of surprise."""
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [SHOP]})  # noqa: E731

    shop = _client(handler).shop_by_owner(87654321)

    assert shop is not None
    assert shop.shop_id == 12345678


def test_a_seller_with_no_shop_is_none_rather_than_an_error() -> None:
    """A seller account without a shop is a real state, and one `setup` can
    ask about -- not a failure to report."""
    handler = lambda _: httpx.Response(404, json={"error": "Shop not found."})  # noqa: E731

    assert _client(handler).shop_by_owner(87654321) is None


def test_any_other_refusal_still_raises() -> None:
    handler = lambda _: httpx.Response(400, json={"error": "bad user id"})  # noqa: E731

    with pytest.raises(EtsyApiError):
        _client(handler).shop_by_owner(87654321)


# ------------------------------------------------- sections and return policies


def test_sections_come_back_with_their_titles() -> None:
    payload = {
        "count": 2,
        "results": [
            {"shop_section_id": 44, "title": "Tees", "rank": 1, "active_listing_count": 12},
            {"shop_section_id": 45, "title": "Hoodies", "rank": 2, "active_listing_count": 3},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/application/shops/12345678/sections"
        return httpx.Response(200, json=payload)

    sections = _client(handler).shop_sections(12345678)

    assert [(s.shop_section_id, s.title) for s in sections] == [(44, "Tees"), (45, "Hoodies")]


def test_return_policies_describe_themselves_since_etsy_gives_them_no_title() -> None:
    """Two policies on one shop are otherwise "1122334" and "1122335", which
    is a coin toss in a picker."""
    payload = {
        "count": 1,
        "results": [
            {
                "return_policy_id": 1122334,
                "shop_id": 12345678,
                "accepts_returns": True,
                "accepts_exchanges": False,
                "return_deadline": 30,
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/application/shops/12345678/policies/return"
        return httpx.Response(200, json=payload)

    policies = _client(handler).return_policies(12345678)

    assert policies[0].describe() == "returns within 30 days"


def test_a_policy_accepting_nothing_says_so() -> None:
    handler = lambda _: httpx.Response(  # noqa: E731
        200,
        json={
            "count": 1,
            "results": [
                {"return_policy_id": 9, "accepts_returns": False, "accepts_exchanges": False}
            ],
        },
    )

    assert _client(handler).return_policies(1)[0].describe() == "no returns or exchanges"


def test_an_unexpected_envelope_reads_as_empty_rather_than_raising() -> None:
    """ "No sections" and "a shape we did not expect" get the same treatment,
    because `setup`'s response to both is to ask."""
    handler = lambda _: httpx.Response(200, json={"unexpected": True})  # noqa: E731

    assert _client(handler).shop_sections(1) == []

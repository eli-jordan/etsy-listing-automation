"""Contract layer for the market search reads: paths, parameters, envelopes,
and the response shapes Etsy actually sends (market-seo.md, *Search* and
*Stats*).

Payloads are trimmed from live responses (September 2026) rather than the API
reference alone, because three measured behaviours make the obvious
implementation wrong: titles and descriptions arrive HTML-escaped
(``Father&#39;s Day``), ``getReviewsByListing``'s ``count`` is the listing's
total however small ``limit`` is, and ``getListingsByListingIds`` answers the
whole batch with a ``404`` when a single id no longer exists.
"""

from __future__ import annotations

import httpx
import pytest

from etsy_listings.clients.etsy.market import HttpEtsyMarketClient
from etsy_listings.clients.etsy.transport import BASE_URL as ETSY_BASE_URL
from etsy_listings.clients.etsy.transport import EtsyApiError
from etsy_listings.clients.etsy.transport import Transport as EtsyTransport
from etsy_listings.config.secrets import EtsyAppKey

from tests.support.http import etsy_transport

SEARCH_ROW = {
    "listing_id": 1406100023,
    "user_id": 1,
    "shop_id": 20025200,
    "title": "Blue Ridge Mountains Sweatshirt, Father&#39;s Day Gift",
    "description": "Celebrate Dad&#39;s trail days.\n\nPrinted to order.",
    "state": "active",
    "original_creation_timestamp": 1675076729,
    "creation_timestamp": 1716000000,
    "url": "https://www.etsy.com/listing/1406100023/blue-ridge-mountains-sweatshirt",
    "num_favorers": 6,
    "views": 462,
    "tags": ["hiking shirt", "retro sunset", "dad&#39;s gift"],
    "price": {"amount": 3499, "divisor": 100, "currency_code": "USD"},
}


def _client(handler) -> HttpEtsyMarketClient:  # noqa: ANN001 - a test handler
    return HttpEtsyMarketClient(etsy_transport(handler, bearer=None))


# ------------------------------------------------------------ search_active


def test_a_search_asks_for_the_listings_a_us_buyer_would_see_in_relevance_order() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"count": 1, "results": [SEARCH_ROW]})

    _client(handler).search_active("retro sunset hiking shirt")

    assert seen == {
        "path": "/v3/application/listings/active",
        "params": {
            "keywords": "retro sunset hiking shirt",
            "sort_on": "score",
            "limit": "25",
            "buyer_country": "US",
        },
    }


def test_a_search_decodes_each_row_into_a_candidate_in_etsys_order() -> None:
    second = {**SEARCH_ROW, "listing_id": 222, "shop_id": 9}
    handler = lambda _: httpx.Response(  # noqa: E731
        200, json={"count": 4120, "results": [SEARCH_ROW, second]}
    )

    found = _client(handler).search_active("hiking shirt")

    assert [c.listing_id for c in found] == [1406100023, 222]
    first = found[0]
    assert first.shop_id == 20025200
    assert first.num_favorers == 6
    assert first.views == 462
    assert first.original_creation_timestamp == 1675076729
    assert first.url == "https://www.etsy.com/listing/1406100023/blue-ridge-mountains-sweatshirt"


def test_html_entities_in_titles_descriptions_and_tags_are_decoded() -> None:
    """Measured: Etsy escapes an apostrophe as ``&#39;`` in all three. Left
    in, ``father&#39;s day`` becomes a phrase no buyer has ever typed, and
    the model is shown it as buyer vocabulary."""
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [SEARCH_ROW]})  # noqa: E731

    [candidate] = _client(handler).search_active("hiking shirt")

    assert candidate.title == "Blue Ridge Mountains Sweatshirt, Father's Day Gift"
    assert candidate.description == "Celebrate Dad's trail days.\n\nPrinted to order."
    assert candidate.tags == ("hiking shirt", "retro sunset", "dad's gift")


OPTIONAL_FIELDS = (
    "title",
    "description",
    "tags",
    "num_favorers",
    "views",
    "original_creation_timestamp",
    "url",
)


@pytest.mark.parametrize("absence", ["missing", "null"])
def test_a_row_without_its_optional_fields_still_decodes(absence: str) -> None:
    """Etsy documents ``tags`` as defaulting to null, and a listing that was
    never viewed can carry no ``views``. One sparse row must not fail a whole
    search."""
    sparse: dict[str, object] = {"listing_id": 7, "shop_id": 8}
    if absence == "null":
        sparse |= dict.fromkeys(OPTIONAL_FIELDS)
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [sparse]})  # noqa: E731

    [candidate] = _client(handler).search_active("hiking shirt")

    assert candidate.title == ""
    assert candidate.description == ""
    assert candidate.tags == ()
    assert candidate.num_favorers == 0
    assert candidate.views == 0
    assert candidate.original_creation_timestamp is None
    assert candidate.url is None


def test_the_creation_time_falls_back_to_the_listings_own_when_the_original_is_absent() -> None:
    row = {"listing_id": 7, "shop_id": 8, "creation_timestamp": 1700000000}
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [row]})  # noqa: E731

    [candidate] = _client(handler).search_active("hiking shirt")

    assert candidate.original_creation_timestamp == 1700000000


def test_a_search_with_no_results_is_an_empty_list() -> None:
    handler = lambda _: httpx.Response(200, json={"count": 0, "results": []})  # noqa: E731

    assert _client(handler).search_active("nothing like this exists") == []


def test_a_search_can_ask_for_fewer_rows() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["limit"])
        return httpx.Response(200, json={"count": 0, "results": []})

    _client(handler).search_active("hiking shirt", limit=5)

    assert seen == ["5"]


# ----------------------------------------------------------- listings_by_ids

BATCH_ROW = {
    **SEARCH_ROW,
    "shop": {
        "shop_id": 20025200,
        "shop_name": "SoulangeDesigns",
        "transaction_sold_count": 5243,
        "review_average": 4.92,
        "review_count": 1852,
        "currency_code": "USD",
    },
    "images": [
        {
            "listing_image_id": 3908130649,
            "rank": 1,
            "url_75x75": "https://i.etsystatic.com/il_75x75.3908130649.jpg",
            "url_170x135": "https://i.etsystatic.com/il_170x135.3908130649.jpg",
            "url_570xN": "https://i.etsystatic.com/il_570xN.3908130649.jpg",
        },
        {
            "listing_image_id": 3908130650,
            "rank": 2,
            "url_170x135": "https://i.etsystatic.com/il_170x135.3908130650.jpg",
        },
    ],
}


def _batch_of(*ids: int) -> dict[str, object]:
    return {
        "count": len(ids),
        "results": [{**BATCH_ROW, "listing_id": i} for i in ids],
    }


def test_the_batch_asks_for_every_id_with_its_shop_and_images() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_batch_of(11, 12))

    _client(handler).listings_by_ids([11, 12])

    assert seen == {
        "path": "/v3/application/listings/batch",
        "params": {"listing_ids": "11,12", "includes": "Shop,Images"},
    }


def test_the_batch_decodes_views_shop_stats_and_the_first_images_thumbnail() -> None:
    handler = lambda _: httpx.Response(200, json=_batch_of(1406100023))  # noqa: E731

    [listing] = _client(handler).listings_by_ids([1406100023])

    assert listing.listing_id == 1406100023
    assert listing.views == 462
    assert listing.title == "Blue Ridge Mountains Sweatshirt, Father's Day Gift"
    assert listing.shop is not None
    assert listing.shop.shop_name == "SoulangeDesigns"
    assert listing.shop.transaction_sold_count == 5243
    assert listing.shop.review_average == 4.92
    assert listing.shop.review_count == 1852
    assert listing.thumbnail_url == "https://i.etsystatic.com/il_170x135.3908130649.jpg"


def test_the_thumbnail_is_the_first_ranked_image_whatever_order_they_arrive_in() -> None:
    row = {**BATCH_ROW, "images": list(reversed(BATCH_ROW["images"]))}
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [row]})  # noqa: E731

    [listing] = _client(handler).listings_by_ids([1406100023])

    assert listing.thumbnail_url == "https://i.etsystatic.com/il_170x135.3908130649.jpg"


def test_a_listing_with_no_images_and_a_shop_with_no_reviews_still_decodes() -> None:
    """A shop with no reviews in the past year sends ``review_average: null``
    -- which scoring must read as *lowest*, so it has to survive decoding as
    ``None`` rather than become a zero that looks like a real rating."""
    row = {
        "listing_id": 5,
        "shop_id": 6,
        "images": [],
        "shop": {"shop_id": 6, "shop_name": "NewShop", "review_average": None},
    }
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [row]})  # noqa: E731

    [listing] = _client(handler).listings_by_ids([5])

    assert listing.thumbnail_url is None
    assert listing.shop is not None
    assert listing.shop.review_average is None
    assert listing.shop.review_count == 0
    assert listing.shop.transaction_sold_count == 0


def test_a_listing_without_its_shop_or_images_keys_still_decodes() -> None:
    row = {"listing_id": 5, "shop_id": 6, "shop": None, "images": None}
    handler = lambda _: httpx.Response(200, json={"count": 1, "results": [row]})  # noqa: E731

    [listing] = _client(handler).listings_by_ids([5])

    assert listing.shop is None
    assert listing.thumbnail_url is None


def test_more_than_a_hundred_ids_are_asked_for_in_chunks_of_a_hundred() -> None:
    chunks: list[list[int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["listing_ids"].split(",")]
        chunks.append(ids)
        return httpx.Response(200, json=_batch_of(*ids))

    listings = _client(handler).listings_by_ids(list(range(1, 251)))

    assert [len(chunk) for chunk in chunks] == [100, 100, 50]
    assert chunks[0][0] == 1 and chunks[2][-1] == 250
    assert [listing.listing_id for listing in listings] == list(range(1, 251))


def test_no_ids_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an empty batch must not reach Etsy")

    assert _client(handler).listings_by_ids([]) == []


def test_a_listing_gone_since_the_search_is_dropped_rather_than_failing_the_batch() -> None:
    """Measured: one id Etsy no longer has turns the *whole* batch into a
    ``404`` naming the missing ids. A listing deactivated between the search
    and this call is ordinary, so the batch is asked again without it, and the
    listing is simply absent from the answer."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.params["listing_ids"]
        asked.append(ids)
        if "13" in ids.split(","):
            return httpx.Response(
                404, json={"error": "Not all requested listings exist. Missing listing_ids: 13."}
            )
        return httpx.Response(200, json=_batch_of(*(int(i) for i in ids.split(","))))

    listings = _client(handler).listings_by_ids([11, 13, 12])

    assert asked == ["11,13,12", "11,12"]
    assert [listing.listing_id for listing in listings] == [11, 12]


def test_a_batch_whose_every_id_is_gone_is_empty() -> None:
    handler = lambda _: httpx.Response(  # noqa: E731
        404, json={"error": "Not all requested listings exist. Missing listing_ids: 1,2."}
    )

    assert _client(handler).listings_by_ids([1, 2]) == []


def test_a_404_that_names_no_missing_ids_is_raised() -> None:
    """Only the one shape we measured is read as "some ids are gone". Any
    other 404 is a failure we do not understand, and guessing would hide it."""
    handler = lambda _: httpx.Response(404, json={"error": "Resource not found"})  # noqa: E731

    with pytest.raises(EtsyApiError) as raised:
        _client(handler).listings_by_ids([1, 2])

    assert raised.value.status_code == 404


# -------------------------------------------------------------- review_count


def test_a_review_count_asks_for_one_review_and_reads_the_total() -> None:
    """Measured: ``count`` is the listing's total however small ``limit`` is,
    so one review's worth of payload buys the whole number."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200, json={"count": 4, "results": [{"listing_id": 4544769975, "rating": 5}]}
        )

    assert _client(handler).review_count(4544769975) == 4
    assert seen == {
        "path": "/v3/application/listings/4544769975/reviews",
        "params": {"limit": "1"},
    }


def test_a_listing_with_no_reviews_counts_zero() -> None:
    handler = lambda _: httpx.Response(200, json={"count": 0, "results": []})  # noqa: E731

    assert _client(handler).review_count(1) == 0


def test_a_listing_gone_since_the_batch_counts_zero_reviews() -> None:
    """Measured: ``Could not find a Listing``. The same ordinary race as the
    batch's -- a listing deactivated mid-research -- and failing the whole run
    for it would block the proposal over one row it can score without."""
    handler = lambda _: httpx.Response(  # noqa: E731
        404, json={"error": "Could not find a Listing with listing_id = 1"}
    )

    assert _client(handler).review_count(1) == 0


def test_a_review_response_without_a_count_is_refused() -> None:
    """Zero would be a guess dressed as data: it scores the listing as
    having no sales evidence at all."""
    handler = lambda _: httpx.Response(200, json={"results": []})  # noqa: E731

    with pytest.raises(EtsyApiError):
        _client(handler).review_count(1)


# --------------------------------------------------- retry classification
#
# market-seo.md, *Failures*: only transient failures are retried -- 429
# (waiting at least as long as Retry-After asks), 5xx, timeouts and network
# errors -- with the Etsy transport's existing policy. Any other 4xx fails
# at once, since retrying cannot fix it.


class _Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.attempts = 0
        self.slept: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        answer = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self) -> HttpEtsyMarketClient:
        return HttpEtsyMarketClient(
            EtsyTransport(
                EtsyAppKey("k", "s"),
                client=httpx.Client(
                    transport=httpx.MockTransport(self.handler), base_url=ETSY_BASE_URL
                ),
                sleep=self.slept.append,
                random=lambda: 0.5,
            )
        )


EMPTY = httpx.Response(200, json={"count": 0, "results": []})


def test_a_429_waits_as_long_as_retry_after_asks_then_succeeds() -> None:
    recorder = _Recorder(
        httpx.Response(429, headers={"Retry-After": "3"}, json={"error": "slow down"}), EMPTY
    )

    assert recorder.client().search_active("hiking shirt") == []
    assert recorder.attempts == 2
    assert recorder.slept == [3.0]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_server_error_is_retried_with_backoff(status: int) -> None:
    recorder = _Recorder(httpx.Response(status, text="<html>busy</html>"), EMPTY)

    assert recorder.client().listings_by_ids([1]) == []
    assert recorder.attempts == 2
    assert recorder.slept == [0.5]


def test_a_network_error_is_retried() -> None:
    recorder = _Recorder(httpx.ConnectError("connection reset"), EMPTY)

    assert recorder.client().review_count(1) == 0
    assert recorder.attempts == 2


@pytest.mark.parametrize("status", [400, 409, 422])
def test_any_other_client_error_fails_at_once(status: int) -> None:
    recorder = _Recorder(httpx.Response(status, json={"error": "keywords is invalid"}))

    with pytest.raises(EtsyApiError) as raised:
        recorder.client().search_active("hiking shirt")

    assert recorder.attempts == 1
    assert raised.value.status_code == status
    assert "keywords is invalid" in str(raised.value)


def test_a_persistent_server_error_gives_up_after_four_attempts_with_its_reason() -> None:
    recorder = _Recorder(httpx.Response(503, json={"error": "upstream unavailable"}))

    with pytest.raises(EtsyApiError) as raised:
        recorder.client().search_active("hiking shirt")

    assert recorder.attempts == 4
    assert recorder.slept == [0.5, 1.0, 2.0]
    assert raised.value.error == "upstream unavailable"


def test_a_persistent_network_error_is_raised_after_four_attempts() -> None:
    recorder = _Recorder(httpx.ReadTimeout("timed out"))

    with pytest.raises(httpx.ReadTimeout):
        recorder.client().review_count(1)

    assert recorder.attempts == 4


def test_a_failing_batch_is_raised_not_read_as_missing_listings() -> None:
    recorder = _Recorder(httpx.Response(500, json={"error": "internal"}))

    with pytest.raises(EtsyApiError) as raised:
        recorder.client().listings_by_ids([1, 2])

    assert raised.value.status_code == 500


def test_a_failing_review_count_is_raised_not_read_as_zero() -> None:
    """Only a vanished listing counts zero. A refusal is a failure the run
    reports, since zero would score the listing as having no sales."""
    recorder = _Recorder(httpx.Response(400, json={"error": "limit is invalid"}))

    with pytest.raises(EtsyApiError):
        recorder.client().review_count(1)


def test_a_search_body_without_the_list_envelope_reads_as_no_results() -> None:
    handler = lambda _: httpx.Response(200, json={"error": None})  # noqa: E731

    assert _client(handler).search_active("hiking shirt") == []

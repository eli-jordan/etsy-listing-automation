"""Contract layer for the listing surface Phase 3's stages write through:
payload shape, both `image_ids` encodings, and the two asymmetric reads
(`GET .../listings/{id}` works, `GET .../shops/{shop}/listings/{id}` 404s;
the images endpoint 404s for every id, valid or invented).

Every payload here is transcribed from a real response recorded on
2026-09-10 (docs/printify-etsy-integration.md, "Phase 3 recon"), including
the parts that make the naive implementation wrong: the comma-separated
`image_ids` encoding versus the repeated-key one that destroys images.
"""

from __future__ import annotations

import httpx
import pytest

from etsy_listings.clients.etsy.listings import HttpEtsyListingClient
from etsy_listings.clients.etsy.transport import EtsyApiError

from tests.support.http import etsy_transport

LISTING_ID = 4572550919
SHOP_ID = 67961328

LISTING_PAYLOAD = {
    "listing_id": LISTING_ID,
    "shop_id": SHOP_ID,
    "state": "draft",
    "title": "OUR COPY - written by the tool, must survive republish",
    "description": "A retro sunset.",
    "tags": ["experiment", "donotbuy"],
    "materials": ["cotton"],
    "shop_section_id": 4455667,
    "shipping_profile_id": 314944410819,
    "return_policy_id": 1513785862328,
    "who_made": "someone_else",
    "when_made": "made_to_order",
    "is_supply": False,
    "should_auto_renew": False,
    "production_partners": [
        {
            "production_partner_id": 5785693,
            "partner_name": "The Print Provider",
            "location": "Miami Gardens, FL",
        }
    ],
    "readiness_state_id": 1513785863458,
    "processing_min": 2,
    "processing_max": 5,
}


def _client(handler) -> HttpEtsyListingClient:  # noqa: ANN001 - a test handler
    return HttpEtsyListingClient(etsy_transport(handler))


# --------------------------------------------------------------- get_listing


def test_a_listing_is_read_from_the_unscoped_path() -> None:
    """The shop-scoped path 404s on GET -- only the unscoped single-listing
    read works (docs/printify-etsy-integration.md)."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=LISTING_PAYLOAD)

    listing = _client(handler).get_listing(LISTING_ID)

    assert seen["path"] == f"/v3/application/listings/{LISTING_ID}"
    assert listing is not None
    assert listing.title == "OUR COPY - written by the tool, must survive republish"


# ------------------------------------------------------------ listing_states


def test_states_are_read_in_one_batch_request() -> None:
    """The listings UI asks about every listing at once. One request with a
    comma-separated `listing_ids`, not one per id -- which is the only reason
    the status badge can be resolved on every page load."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.setdefault("calls", 0)
        seen["calls"] += 1
        seen["path"] = request.url.path
        seen["ids"] = request.url.params.get("listing_ids")
        return httpx.Response(
            200,
            json={
                "count": 2,
                "results": [
                    {**LISTING_PAYLOAD, "listing_id": 111, "state": "active"},
                    {**LISTING_PAYLOAD, "listing_id": 222, "state": "draft"},
                ],
            },
        )

    states = _client(handler).listing_states([111, 222])

    assert seen["calls"] == 1
    assert seen["path"] == "/v3/application/listings/batch"
    assert seen["ids"] == "111,222"
    assert states == {111: "active", 222: "draft"}


def test_an_id_etsy_does_not_answer_for_is_absent_rather_than_guessed_at() -> None:
    """ "We could not find out" and "it is still a draft" are different facts,
    and only the caller knows which way to resolve the difference."""
    handler = lambda _: httpx.Response(  # noqa: E731
        200,
        json={"count": 1, "results": [{**LISTING_PAYLOAD, "listing_id": 111, "state": "active"}]},
    )

    assert _client(handler).listing_states([111, 999]) == {111: "active"}


def test_more_ids_than_the_batch_limit_are_chunked() -> None:
    """Etsy caps `getListingsByListingIds` at 100. Chunking is the client's
    job -- a workspace with 150 listings is not a different question from one
    with five."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("listing_ids"))
        return httpx.Response(200, json={"count": 0, "results": []})

    _client(handler).listing_states(list(range(1, 151)))

    assert len(seen) == 2
    assert len(seen[0].split(",")) == 100
    assert len(seen[1].split(",")) == 50


def test_no_ids_asks_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("an empty id list must not reach the network")

    assert _client(handler).listing_states([]) == {}


def test_a_missing_listing_is_none_not_an_error() -> None:
    handler = lambda _: httpx.Response(404, json={"error": "Listing not found."})  # noqa: E731

    assert _client(handler).get_listing(LISTING_ID) is None


def test_who_made_when_made_is_supply_and_partners_round_trip() -> None:
    listing = _client(lambda _: httpx.Response(200, json=LISTING_PAYLOAD)).get_listing(LISTING_ID)

    assert listing is not None
    assert (listing.who_made, listing.when_made, listing.is_supply) == (
        "someone_else",
        "made_to_order",
        False,
    )
    assert [p.partner_name for p in listing.production_partners] == ["The Print Provider"]


def test_includes_images_asks_for_the_images_param() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["includes"] = request.url.params.get("includes")
        return httpx.Response(
            200,
            json={
                **LISTING_PAYLOAD,
                "images": [
                    {"listing_image_id": 8503331196, "rank": 1, "alt_text": "Black, flat lay"},
                    {"listing_image_id": 8503331086, "rank": 2, "alt_text": ""},
                ],
            },
        )

    listing = _client(handler).get_listing(LISTING_ID, include_images=True)

    assert seen["includes"] == "Images"
    assert listing is not None
    assert [(i.listing_image_id, i.rank) for i in listing.images] == [
        (8503331196, 1),
        (8503331086, 2),
    ]


def test_a_listing_with_no_images_requested_has_an_empty_tuple() -> None:
    listing = _client(lambda _: httpx.Response(200, json=LISTING_PAYLOAD)).get_listing(LISTING_ID)

    assert listing is not None
    assert listing.images == ()


def test_images_is_null_not_omitted_when_not_requested() -> None:
    """Measured: the real API sends ``"images": null``, not an absent key, on
    a call without ``includes=Images``. A missing key falls back to the
    field's own default tuple; an explicit ``null`` does not, and every
    `etsy_listing` re-plan of an already-published listing calls `get_listing`
    this way (no `include_images`) -- so this shape broke every second run
    against a real listing until the model was taught to fold it."""
    listing = _client(
        lambda _: httpx.Response(200, json={**LISTING_PAYLOAD, "images": None})
    ).get_listing(LISTING_ID)

    assert listing is not None
    assert listing.images == ()


# -------------------------------------------------------------- update_listing


def test_update_patches_the_shop_scoped_path_with_only_what_changed() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=LISTING_PAYLOAD)

    _client(handler).update_listing(SHOP_ID, LISTING_ID, {"title": "New title"})

    assert (seen["method"], seen["path"]) == (
        "PATCH",
        f"/v3/application/shops/{SHOP_ID}/listings/{LISTING_ID}",
    )
    assert seen["body"] == {"title": "New title"}


def test_update_returns_the_patched_listing() -> None:
    listing = _client(lambda _: httpx.Response(200, json=LISTING_PAYLOAD)).update_listing(
        SHOP_ID, LISTING_ID, {"title": "x"}
    )

    assert listing.listing_id == LISTING_ID


def test_image_ids_are_sent_as_one_comma_separated_value_never_repeated_keys() -> None:
    """The sharp edge, measured: repeated `image_ids` keys answer `200` and
    destroy every image but one. Comma-separated is the only safe encoding."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=LISTING_PAYLOAD)

    _client(handler).update_listing(SHOP_ID, LISTING_ID, {"image_ids": [111, 222, 333]})

    assert seen["body"]["image_ids"] == "111,222,333"


# --------------------------------------------------------- upload_listing_image


def test_upload_posts_multipart_with_rank_and_alt_text() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(
            201, json={"listing_image_id": 8503578806, "rank": 1, "alt_text": "Black, flat lay"}
        )

    image = _client(handler).upload_listing_image(
        SHOP_ID,
        LISTING_ID,
        file_name="flat-lay-black.png",
        contents=b"\x89PNG-bytes",
        rank=1,
        alt_text="Black, flat lay",
    )

    assert (seen["method"], seen["path"]) == (
        "POST",
        f"/v3/application/shops/{SHOP_ID}/listings/{LISTING_ID}/images",
    )
    assert seen["content_type"].startswith("multipart/form-data")
    assert image.listing_image_id == 8503578806


def test_overwrite_replaces_in_place_at_an_occupied_rank() -> None:
    """Measured: `overwrite: true` at rank 1 against three existing images
    leaves the count and the other ranks untouched, minting a new id at rank
    1 rather than colliding with what was there."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["form"] = dict(request.url.params) | _multipart_fields(request)
        return httpx.Response(201, json={"listing_image_id": 8503578806, "rank": 1})

    _client(handler).upload_listing_image(
        SHOP_ID,
        LISTING_ID,
        file_name="flat-lay-black.png",
        contents=b"\x89PNG-bytes",
        rank=1,
        overwrite=True,
        listing_image_id=8503331196,
    )

    assert seen["form"]["overwrite"] == "true"
    assert seen["form"]["listing_image_id"] == "8503331196"


def _multipart_fields(request: httpx.Request) -> dict[str, str]:
    """Decode the non-file fields of a multipart body for assertion."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    parts = request.read().split(b"--" + boundary)
    fields: dict[str, str] = {}
    for part in parts:
        if b'name="' not in part or b"filename=" in part:
            continue
        name = part.split(b'name="')[1].split(b'"')[0].decode()
        value = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0].decode()
        fields[name] = value
    return fields


# -------------------------------------------------------------- get_listing_inventory


def test_inventory_reads_the_colour_property_and_its_values() -> None:
    payload = {
        "products": [
            {
                "product_id": 1,
                "sku": "auto-1",
                "property_values": [
                    {
                        "property_id": 513,
                        "property_name": "Comfort Colors® Colors",
                        "value_ids": [50135267836],
                        "values": ["Black"],
                    },
                    {
                        "property_id": 514,
                        "property_name": "Clothing sizes",
                        "value_ids": [100],
                        "values": ["S"],
                    },
                ],
                "offerings": [{"offering_id": 1, "quantity": 999, "is_enabled": True}],
            }
        ]
    }

    inventory = _client(lambda _: httpx.Response(200, json=payload)).get_listing_inventory(
        LISTING_ID
    )

    colour = next(p for p in inventory.products[0].property_values if p.property_id == 513)
    assert (colour.value_ids, colour.values) == ((50135267836,), ("Black",))


# --------------------------------------------------------- variation images


def test_update_variation_images_posts_the_triples_to_the_shop_scoped_path() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json={"count": 1, "results": []})

    from etsy_listings.clients.etsy.models import VariationImageLink

    _client(handler).update_variation_images(
        SHOP_ID,
        LISTING_ID,
        [VariationImageLink(property_id=513, value_id=50135267836, image_id=8503331196)],
    )

    assert (seen["method"], seen["path"]) == (
        "POST",
        f"/v3/application/shops/{SHOP_ID}/listings/{LISTING_ID}/variation-images",
    )
    assert seen["body"]["variation_images"] == [
        {"property_id": 513, "value_id": 50135267836, "image_id": 8503331196}
    ]


def test_an_empty_list_clears_the_links() -> None:
    """Measured: an empty array is a `200` that clears every link, not a
    no-op. Turning the feature off is a write."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json={"count": 0, "results": []})

    _client(handler).update_variation_images(SHOP_ID, LISTING_ID, [])

    assert seen["body"]["variation_images"] == []


def test_get_listing_variation_images_reads_the_value_string_back() -> None:
    """The read carries the value string alongside each id, so
    `value_id -> value -> slug` comes free with it -- the inventory read is
    needed only to build a link, never to compare one.

    The path is asserted here and not only in the write's test: this read is
    shop-scoped, unlike every other read in this client, and the version that
    left `shop_id` out 404'd for every listing while looking exactly like
    "no links yet".
    """
    payload = {
        "count": 1,
        "results": [
            {
                "property_id": 513,
                "value_id": 50135267836,
                "value": "Black",
                "image_id": 8503331196,
            }
        ],
    }
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json=payload)

    links = _client(handler).get_listing_variation_images(SHOP_ID, LISTING_ID)

    assert (seen["method"], seen["path"]) == (
        "GET",
        f"/v3/application/shops/{SHOP_ID}/listings/{LISTING_ID}/variation-images",
    )
    assert links[0].value == "Black"
    assert links[0].image_id == 8503331196


def test_a_listing_with_no_links_reads_as_an_empty_count() -> None:
    """Measured on the shop-scoped path: a listing that has never had
    `updateVariationImages` called on it answers `200` with `count: 0`, the
    same envelope as every other list read here. The unscoped path's blanket
    `404` was once mistaken for this state, which is why it is pinned."""
    handler = lambda _: httpx.Response(200, json={"count": 0, "results": []})  # noqa: E731

    assert _client(handler).get_listing_variation_images(SHOP_ID, LISTING_ID) == []


def test_a_missing_listing_raises_rather_than_reading_as_no_links() -> None:
    """The other half of the same fix: with the path correct, a `404` is the
    listing being gone, and flattening it to `[]` would report a deleted
    listing as one whose swatches simply are not set."""
    handler = lambda _: httpx.Response(404, json={"error": "Listing not found."})  # noqa: E731

    with pytest.raises(EtsyApiError):
        _client(handler).get_listing_variation_images(SHOP_ID, LISTING_ID)


# --------------------------------------------------- shipping profiles & partners


def test_shipping_profiles_are_read_from_the_shop_scoped_path() -> None:
    payload = {
        "count": 1,
        "results": [
            {
                "shipping_profile_id": 314944410819,
                "title": "Standard: Monster Digital, T-Shirt",
                "origin_country_iso": "US",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v3/application/shops/{SHOP_ID}/shipping-profiles"
        return httpx.Response(200, json=payload)

    profiles = _client(handler).shipping_profiles(SHOP_ID)

    assert profiles[0].title == "Standard: Monster Digital, T-Shirt"


def test_production_partners_are_read_from_the_shop_scoped_path() -> None:
    payload = {
        "count": 1,
        "results": [
            {
                "production_partner_id": 5785693,
                "partner_name": "The Print Provider",
                "location": "Miami Gardens, FL",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v3/application/shops/{SHOP_ID}/production-partners"
        return httpx.Response(200, json=payload)

    partners = _client(handler).production_partners(SHOP_ID)

    assert partners[0].partner_name == "The Print Provider"


def test_shop_sections_are_also_reachable_over_the_signed_in_connection() -> None:
    """Unscoped, and duplicated from `EtsyShopClient` on purpose: the run
    context that resolves a listing carries only `EtsyListingClient`
    (decision 2), not a second client just to reach two unscoped reads over
    the same transport."""
    payload = {"count": 1, "results": [{"shop_section_id": 44, "title": "Retro Tees"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v3/application/shops/{SHOP_ID}/sections"
        return httpx.Response(200, json=payload)

    sections = _client(handler).shop_sections(SHOP_ID)

    assert sections[0].title == "Retro Tees"


def test_return_policies_are_also_reachable_over_the_signed_in_connection() -> None:
    payload = {
        "count": 1,
        "results": [
            {
                "return_policy_id": 1513785862328,
                "accepts_returns": True,
                "accepts_exchanges": True,
                "return_deadline": 30,
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v3/application/shops/{SHOP_ID}/policies/return"
        return httpx.Response(200, json=payload)

    policies = _client(handler).return_policies(SHOP_ID)

    assert policies[0].describe() == "returns and exchanges within 30 days"

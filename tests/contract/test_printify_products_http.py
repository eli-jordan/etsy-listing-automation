"""Contract layer for the product and upload calls: payload shape and the
projection that keeps a comparison honest.

Every payload here is transcribed from a real response recorded on 2026-09-08
(docs/api-findings.md), including the parts that make the naive
implementation wrong: the product comes back carrying the *whole* blueprint
matrix, the placed image gains nine fields we never sent, and an unused
placeholder arrives empty rather than absent.
"""

from __future__ import annotations

import base64

import httpx

from etsy_listings.clients.printify import HttpPrintifyClient
from etsy_listings.clients.printify.models import (
    PlacedImage,
    Placeholder,
    PrintAreaSpec,
    ProductSpec,
)

from tests.support.http import INSTANT, transport

SHOP_ID = 28819281
PRODUCT_ID = "6a9ffdbfecfdc9324d023442"
UPLOAD_ID = "6a9ffd8a2c8e5a0d3f1b0c11"


def _variant(id: int, *, enabled: bool, price: int = 2499, sku: str = "auto-1") -> dict:
    return {
        "id": id,
        "sku": sku,
        "cost": 1304,
        "price": price,
        "title": f"Colour / {id}",
        "grams": 130,
        "is_enabled": enabled,
        "is_default": False,
        "is_available": True,
        "is_printify_express_eligible": False,
        "options": [2767, 14],
        "quantity": 1,
    }


PLACED_IMAGE = {
    # We send five of these. Printify returns fourteen.
    "id": UPLOAD_ID,
    "x": 0.5,
    "y": 0.5,
    "scale": 1.0,
    "angle": 0,
    "name": "probe.png",
    "type": "image/png",
    "width": 4200,
    "height": 4800,
    "flipX": False,
    "flipY": False,
    "src": "https://images.printify.com/...",
    "layerType": "image",
    "imageId": "a-different-id-entirely",
}

PRODUCT_PAYLOAD = {
    "id": PRODUCT_ID,
    "title": "Take A Hike Tee",
    "description": "A retro sunset.",
    "blueprint_id": 706,
    "print_provider_id": 29,
    "visible": False,
    "is_locked": False,
    "tags": ["Unisex", "DTG", "Streetwear"],
    "variants": [
        _variant(73196, enabled=True, price=29900),
        _variant(73200, enabled=True, price=29900),
        _variant(99999, enabled=False, price=1304),
    ],
    "print_areas": [
        {
            "variant_ids": [73196, 73200, 99999],
            "placeholders": [
                {"position": "front", "images": [PLACED_IMAGE]},
                {"position": "back", "images": []},
            ],
        }
    ],
}


def _client(handler) -> HttpPrintifyClient:
    return HttpPrintifyClient(transport(handler, policy=INSTANT))


SPEC = ProductSpec(
    title="Take A Hike Tee",
    description="A retro sunset.",
    blueprint_id=706,
    print_provider_id=29,
    variants={73196: 29900, 73200: 29900},
    print_areas=(
        PrintAreaSpec(
            variant_ids=(73196, 73200),
            placeholders=(Placeholder(position="front", images=(PlacedImage(id=UPLOAD_ID),)),),
        ),
    ),
)


# ------------------------------------------------------------------- uploads


def test_an_upload_sends_base64_contents_and_returns_the_id() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read()
        return httpx.Response(
            200,
            json={"id": UPLOAD_ID, "file_name": "d.png", "width": 4200, "height": 4800},
        )

    upload = _client(handler).upload_image("d.png", b"\x89PNG-bytes")

    assert seen["path"] == "/v1/uploads/images.json"
    assert base64.b64decode(httpx.Response(200, content=seen["body"]).json()["contents"]) == (
        b"\x89PNG-bytes"
    )
    assert upload.id == UPLOAD_ID
    assert (upload.width, upload.height) == (4200, 4800)


# ---------------------------------------------------------------- create/read


def test_create_posts_to_the_shop_and_returns_the_product() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=PRODUCT_PAYLOAD)

    product = _client(handler).create_product(SHOP_ID, SPEC)

    assert (seen["method"], seen["path"]) == ("POST", f"/v1/shops/{SHOP_ID}/products.json")
    assert product.id == PRODUCT_ID


def test_a_create_body_lists_only_the_variants_being_created() -> None:
    """On create, `print_areas.variant_ids` covers the variants being created.
    On update it must cover every variant the product has -- the same payload
    is rejected as an update of the product it made (docs/api-findings.md)."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=PRODUCT_PAYLOAD)

    _client(handler).create_product(SHOP_ID, SPEC)

    assert seen["body"]["print_areas"][0]["variant_ids"] == [73196, 73200]
    assert [v["id"] for v in seen["body"]["variants"]] == [73196, 73200]


def test_every_variant_in_the_body_carries_a_price() -> None:
    """Measured: `{id, is_enabled}` alone is a 400. A variant entry is never
    partial, not even one being switched off."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=PRODUCT_PAYLOAD)

    _client(handler).create_product(SHOP_ID, SPEC)

    assert all("price" in v for v in seen["body"]["variants"])


def test_a_created_product_is_hidden() -> None:
    """`visible` is writable despite the reference marking it read-only. A
    product that has not been reviewed has no business being visible."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=PRODUCT_PAYLOAD)

    _client(handler).create_product(SHOP_ID, SPEC)

    assert seen["body"]["visible"] is False


def test_get_product_returns_none_for_a_product_that_is_gone() -> None:
    """Deleted in Printify's UI between runs is a normal thing to happen, and
    it means "create one", not "crash"."""
    assert (
        _client(lambda _: httpx.Response(404, json={"message": "Not Found"})).get_product(
            SHOP_ID, PRODUCT_ID
        )
        is None
    )


# ------------------------------------------------------------ the projection


def test_only_enabled_variants_survive_the_projection() -> None:
    """The product returns the whole blueprint matrix -- 238 for a product
    created with 6. Comparing that against desired is a diff of 238 against 6,
    forever."""
    product = _client(lambda _: httpx.Response(200, json=PRODUCT_PAYLOAD)).get_product(
        SHOP_ID, PRODUCT_ID
    )

    assert product is not None
    assert product.enabled_variants() == {73196: 29900, 73200: 29900}


def test_the_placement_is_projected_to_the_five_fields_we_set() -> None:
    """We send five; fourteen come back, including an `imageId` distinct from
    the upload id. Comparing all of them is a permanent spurious diff."""
    product = _client(lambda _: httpx.Response(200, json=PRODUCT_PAYLOAD)).get_product(
        SHOP_ID, PRODUCT_ID
    )

    assert product is not None
    placed = product.print_areas[0].placeholders[0].images[0]
    assert placed.model_dump() == {
        "id": UPLOAD_ID,
        "x": 0.5,
        "y": 0.5,
        "scale": 1.0,
        "angle": 0,
    }


def test_an_empty_placeholder_is_dropped_from_the_projection() -> None:
    """We send `front`; `back` comes back with `images: []`. A placeholder we
    never placed anything in is not a difference."""
    product = _client(lambda _: httpx.Response(200, json=PRODUCT_PAYLOAD)).get_product(
        SHOP_ID, PRODUCT_ID
    )

    assert product is not None
    assert [p.position for p in product.print_areas[0].placeholders] == ["front"]


def test_visible_is_kept_as_a_tripwire() -> None:
    product = _client(lambda _: httpx.Response(200, json=PRODUCT_PAYLOAD)).get_product(
        SHOP_ID, PRODUCT_ID
    )

    assert product is not None and product.visible is False


def test_external_is_absent_rather_than_null_before_a_publish() -> None:
    product = _client(lambda _: httpx.Response(200, json=PRODUCT_PAYLOAD)).get_product(
        SHOP_ID, PRODUCT_ID
    )

    assert product is not None and product.external is None


# ----------------------------------------------------------------- the update


def test_an_update_covers_every_variant_the_product_has() -> None:
    """The coverage rule. The union across all print_areas must name all 238
    or Printify answers 400 code 8251 -- which is why an update has to read
    the product before it can write it."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=PRODUCT_PAYLOAD)
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=PRODUCT_PAYLOAD)

    client = _client(handler)
    live = client.get_product(SHOP_ID, PRODUCT_ID)
    assert live is not None
    client.update_product(SHOP_ID, PRODUCT_ID, SPEC, live=live)

    assert set(seen["body"]["print_areas"][0]["variant_ids"]) == {73196, 73200, 99999}


def test_an_update_disables_what_the_spec_dropped() -> None:
    """Omission means "no opinion", not "off" -- a `PUT` carrying three of six
    enabled variants left all six enabled. A dropped colour would keep
    selling."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=PRODUCT_PAYLOAD)
        seen["body"] = httpx.Response(200, content=request.read()).json()
        return httpx.Response(200, json=PRODUCT_PAYLOAD)

    client = _client(handler)
    live = client.get_product(SHOP_ID, PRODUCT_ID)
    assert live is not None
    narrowed = SPEC.model_copy(update={"variants": {73196: 29900}})
    client.update_product(SHOP_ID, PRODUCT_ID, narrowed, live=live)

    by_id = {v["id"]: v for v in seen["body"]["variants"]}
    assert by_id[73196]["is_enabled"] is True
    assert by_id[73200]["is_enabled"] is False, "explicitly retired, not merely omitted"
    assert "price" in by_id[73200], "a disabled variant still needs a price (400 otherwise)"


# --------------------------------------------------------- the duplicate walk


def _page(products: list[dict], *, page: int, last: int) -> dict:
    return {"current_page": page, "last_page": last, "per_page": 50, "data": products}


def test_the_walk_finds_a_product_matching_title_and_description() -> None:
    """PRD 48. There is no natural key and no filter -- `title`, `search` and
    `sku` are all accepted and ignored -- so the match is client-side."""
    found = _client(
        lambda _: httpx.Response(200, json=_page([PRODUCT_PAYLOAD], page=1, last=1))
    ).find_product_by_copy(SHOP_ID, title="Take A Hike Tee", description="A retro sunset.")

    assert found == PRODUCT_ID


def test_the_walk_returns_none_when_nothing_matches() -> None:
    found = _client(
        lambda _: httpx.Response(200, json=_page([PRODUCT_PAYLOAD], page=1, last=1))
    ).find_product_by_copy(SHOP_ID, title="Something Else", description="A retro sunset.")

    assert found is None


def test_the_description_has_to_match_too() -> None:
    """Title alone would collide across a shop selling the same design on two
    garments."""
    found = _client(
        lambda _: httpx.Response(200, json=_page([PRODUCT_PAYLOAD], page=1, last=1))
    ).find_product_by_copy(SHOP_ID, title="Take A Hike Tee", description="Different.")

    assert found is None


def test_the_walk_follows_every_page() -> None:
    pages = {
        1: _page([{**PRODUCT_PAYLOAD, "id": "other", "title": "Other"}], page=1, last=2),
        2: _page([PRODUCT_PAYLOAD], page=2, last=2),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        requested.append(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages[page])

    found = _client(handler).find_product_by_copy(
        SHOP_ID, title="Take A Hike Tee", description="A retro sunset."
    )

    assert found == PRODUCT_ID
    assert requested == ["1", "2"]


def test_the_walk_stops_at_the_last_page_rather_than_looping() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_page([], page=1, last=1))

    assert _client(handler).find_product_by_copy(SHOP_ID, title="x", description="y") is None
    assert len(calls) == 1


def test_a_deleted_product_is_not_a_match() -> None:
    """`is_deleted` products stay in the list. Adopting one would bind the
    lockfile to a product that cannot be updated."""
    deleted = {**PRODUCT_PAYLOAD, "is_deleted": True}

    found = _client(
        lambda _: httpx.Response(200, json=_page([deleted], page=1, last=1))
    ).find_product_by_copy(SHOP_ID, title="Take A Hike Tee", description="A retro sunset.")

    assert found is None


def test_delete_removes_the_product() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["path"] = request.method, request.url.path
        return httpx.Response(200, json={})

    _client(handler).delete_product(SHOP_ID, PRODUCT_ID)

    assert seen == {
        "method": "DELETE",
        "path": f"/v1/shops/{SHOP_ID}/products/{PRODUCT_ID}.json",
    }

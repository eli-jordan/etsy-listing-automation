"""Creating a Printify product, against the real API. ``-m e2e``, skipped by default.

Phase 2 recon. Nothing in ``src/`` creates products yet, and this file is how
that gets specified: it asks the live API what a product actually requires,
what it gives back, and what an *update* does to what is already there --
because the ``printify_product`` stage's whole job is to answer "does live
match desired?", and half the answers below are not the obvious ones.

The four that would each have produced a plausible-looking, wrong stage:

- The product comes back carrying **every** variant of the blueprint/provider
  pair, not the handful sent. Comparing the returned list against desired is
  therefore a diff of 238 against 6.
- ``variants`` on an update **merges by id**. Omitting a variant does not
  disable it; only an explicit ``is_enabled: false`` does. A listing that
  drops a colour would silently keep selling it.
- ``print_areas.*.variant_ids`` must cover **every product variant** on an
  update, though on create it covers only the ones being created. The same
  payload that created the product is rejected as an update of it.
- ``visible`` is writable, on create and on update, despite the API reference
  marking it read-only -- see ``docs/api-findings.md``.

It talks to the API through raw ``httpx`` rather than a client, because the
client is what this is recon *for*; when ``clients/printify/`` exists these
move onto it and the payload shapes below become its cassettes.

**This layer costs state.** It creates exactly one product and deletes it in
teardown, in the shop named by ``PRINTIFY_SHOP_ID`` (or the account's only
shop). Nothing here publishes to a sales channel.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw

from etsy_listings.catalog.http import HttpCatalogClient
from etsy_listings.catalog.models import Blueprint, PrintProvider, VariantSet
from etsy_listings.catalog.resolve import resolve_blueprint

pytestmark = pytest.mark.e2e

GARMENT_BRAND = "Comfort Colors"
GARMENT_MODEL = "1717"
PREFERRED_PROVIDER = "Monster Digital"
"""The blank and printer this shop actually sells, matching the workspace's
``preferred_print_provider``. Identified by brand and model, never by title --
PRD 23, and ``test_printify_catalog_e2e.py`` for why."""

COLOURS = ("Black", "Ivory")
SIZES = ("S", "M", "L")
"""Two colours by three sizes: enough for the variant matrix to be a matrix
and for a per-colour print area to have two sides, small enough to read in a
failure message."""

PRICE = 2499
"""USD cents -- $24.99. The API says so nowhere; Printify's web app does, and
``docs/api-findings.md`` records it (PRD 39)."""


# --------------------------------------------------------------- the design


def _test_design(size: tuple[int, int]) -> bytes:
    """A deterministic PNG. Uploads are content-addressed (proved below), so a
    generator with no clock or randomness in it means a re-run reuses the
    upload it made last time instead of accumulating one per run."""
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [0, 0, width - 1, height - 1], outline=(20, 20, 20, 255), width=max(2, width // 100)
    )
    draw.ellipse(
        [width // 4, height // 4, width * 3 // 4, height * 3 // 4], fill=(200, 40, 40, 255)
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(api: httpx.Client, name: str, payload: bytes) -> dict[str, Any]:
    response = api.post(
        "/uploads/images.json",
        json={"file_name": name, "contents": base64.b64encode(payload).decode()},
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------- the fixtures


@pytest.fixture(scope="session")
def garment(catalog: HttpCatalogClient) -> Blueprint:
    return resolve_blueprint(GARMENT_BRAND, GARMENT_MODEL, catalog.blueprints())


@pytest.fixture(scope="session")
def provider(catalog: HttpCatalogClient, garment: Blueprint) -> PrintProvider:
    providers = catalog.print_providers(garment.id)
    assert providers, f"no print providers for blueprint {garment.id}"
    return next((p for p in providers if p.title == PREFERRED_PROVIDER), providers[0])


@pytest.fixture(scope="session")
def variants(catalog: HttpCatalogClient, garment: Blueprint, provider: PrintProvider) -> VariantSet:
    return catalog.variants(garment.id, provider.id)


@pytest.fixture(scope="session")
def wanted_variant_ids(variants: VariantSet) -> list[int]:
    """The colour x size matrix this product sells, resolved the way the
    ``printify_product`` stage will have to: catalog colour and size names to
    integer variant ids."""
    wanted = {(colour, size) for colour in COLOURS for size in SIZES}
    chosen = [v.id for v in variants.variants if (v.options.color, v.options.size) in wanted]
    assert len(chosen) == len(wanted), (
        f"expected {len(wanted)} variants for {COLOURS} x {SIZES}, resolved {len(chosen)}"
    )
    return sorted(chosen)


@pytest.fixture(scope="session")
def design(printify_api: httpx.Client) -> dict[str, Any]:
    """A print file at a plausible resolution for the 4200x4800 print area.
    Not *at* it: the point of the upload is the API contract, and the bytes
    would be four megabytes of nothing."""
    return _upload(printify_api, "e2e-test-design.png", _test_design((1200, 1440)))


@pytest.fixture(scope="session")
def create_spec(
    garment: Blueprint,
    provider: PrintProvider,
    wanted_variant_ids: list[int],
    design: dict[str, Any],
) -> dict[str, Any]:
    """Every data element Printify needs to make a product. This is the shape
    ``ProductSpec`` has to serialise to."""
    return {
        "title": "etsy-listings e2e -- safe to delete",
        "description": "Created by an automated test. Deleted in teardown.",
        "blueprint_id": garment.id,
        "print_provider_id": provider.id,
        "variants": [
            {"id": variant_id, "price": PRICE, "is_enabled": True}
            for variant_id in wanted_variant_ids
        ],
        "print_areas": [
            {
                "variant_ids": wanted_variant_ids,
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            {
                                "id": design["id"],
                                "x": 0.5,
                                "y": 0.5,
                                "scale": 1.0,
                                "angle": 0,
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture(scope="session")
def product(
    printify_api: httpx.Client, printify_shop: dict[str, Any], create_spec: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """One product for the whole session, deleted afterwards whatever happens.

    Session-scoped and mutated in place by the update tests below, each of
    which restores what it changed. A per-test product would be tidier and
    would cost a create, a delete and Printify's mockup generation per
    assertion."""
    shop_id = printify_shop["id"]
    response = printify_api.post(f"/shops/{shop_id}/products.json", json=create_spec)
    assert response.status_code == 200, f"create failed: {response.status_code} {response.text}"
    created: dict[str, Any] = response.json()
    try:
        yield created
    finally:
        deleted = printify_api.delete(f"/shops/{shop_id}/products/{created['id']}.json")
        assert deleted.status_code == 200, (
            f"the throwaway product {created['id']} was left behind: "
            f"{deleted.status_code} {deleted.text}"
        )


@pytest.fixture
def live(
    printify_api: httpx.Client, printify_shop: dict[str, Any], product: dict[str, Any]
) -> dict[str, Any]:
    """The product as Printify holds it now -- what ``read_live()`` will do."""
    response = printify_api.get(f"/shops/{printify_shop['id']}/products/{product['id']}.json")
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
def reread(printify_api: httpx.Client, printify_shop: dict[str, Any], product: dict[str, Any]):
    """``live`` again, for tests that need the state *after* their own write."""

    def _reread() -> dict[str, Any]:
        response = printify_api.get(f"/shops/{printify_shop['id']}/products/{product['id']}.json")
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    return _reread


@pytest.fixture
def disconnected(printify_shop: dict[str, Any]) -> None:
    """Guards the tests that POST to ``publish.json``. On a shop with a sales
    channel connected that call creates a real listing, which is not a thing a
    test may do to somebody's store."""
    if printify_shop["sales_channel"] != "disconnected":
        pytest.skip(
            f"this shop is connected to {printify_shop['sales_channel']}; "
            f"publishing here would create a real listing"
        )


@pytest.fixture
def update(printify_api: httpx.Client, printify_shop: dict[str, Any], product: dict[str, Any]):
    """PUT a partial body and hand back the response, decoded."""

    def _update(body: dict[str, Any], *, expect: int = 200) -> dict[str, Any]:
        response = printify_api.put(
            f"/shops/{printify_shop['id']}/products/{product['id']}.json", json=body
        )
        assert response.status_code == expect, f"{response.status_code}: {response.text}"
        decoded: dict[str, Any] = response.json()
        return decoded

    return _update


def _enabled(product: dict[str, Any]) -> list[int]:
    return sorted(v["id"] for v in product["variants"] if v["is_enabled"])


def _front_images(product: dict[str, Any]) -> list[dict[str, Any]]:
    front = [
        placeholder
        for area in product["print_areas"]
        for placeholder in area["placeholders"]
        if placeholder["position"] == "front"
    ]
    return [image for placeholder in front for image in placeholder["images"]]


# ------------------------------------------------------------- the contract


class TestUploadingTheDesign:
    """``POST /v1/uploads/images.json`` -- the step before a product exists."""

    def test_it_returns_an_id_and_the_decoded_dimensions(self, design: dict[str, Any]) -> None:
        assert design["id"]
        assert (design["width"], design["height"]) == (1200, 1440)
        assert design["mime_type"] == "image/png"

    def test_the_same_bytes_upload_to_the_same_id(
        self, printify_api: httpx.Client, design: dict[str, Any]
    ) -> None:
        """Uploads are content-addressed, so re-uploading is safe rather than
        merely wasteful -- but it still ships the file, so the stage caches the
        id in the lockfile and skips the call."""
        again = _upload(printify_api, "e2e-test-design.png", _test_design((1200, 1440)))
        assert again["id"] == design["id"]
        assert again["upload_time"] == design["upload_time"]

    def test_the_file_name_takes_no_part_in_that(
        self, printify_api: httpx.Client, design: dict[str, Any]
    ) -> None:
        renamed = _upload(printify_api, "some-other-name.png", _test_design((1200, 1440)))
        assert renamed["id"] == design["id"]

    def test_an_image_far_below_print_resolution_is_accepted(
        self, printify_api: httpx.Client
    ) -> None:
        """120x140 on a 4200x4800 print area. Printify takes it without a
        murmur, which is why the PRD's design validation (17) is a real gate
        and not a courtesy: nothing downstream will catch a blurry print."""
        tiny = _upload(printify_api, "e2e-tiny.png", _test_design((120, 140)))
        assert tiny["id"]
        assert (tiny["width"], tiny["height"]) == (120, 140)


class TestCreatingTheProduct:
    """``POST /v1/shops/{shop}/products.json`` -- what comes back."""

    def test_it_returns_a_string_id(self, product: dict[str, Any]) -> None:
        """Not an integer, unlike every other id in this API. The lockfile's
        ``remote.printify_product_id`` is a string for this reason."""
        assert isinstance(product["id"], str)

    def test_the_blueprint_and_provider_come_back_as_sent(
        self, live: dict[str, Any], garment: Blueprint, provider: PrintProvider
    ) -> None:
        assert live["blueprint_id"] == garment.id
        assert live["print_provider_id"] == provider.id

    def test_exactly_the_requested_variants_are_enabled(
        self, live: dict[str, Any], wanted_variant_ids: list[int]
    ) -> None:
        assert _enabled(live) == wanted_variant_ids

    def test_but_the_whole_blueprint_matrix_comes_back_with_them(
        self, live: dict[str, Any], wanted_variant_ids: list[int], variants: VariantSet
    ) -> None:
        """The single most misleading thing about this response. A product
        created with six variants returns every variant of the pair -- the
        catalog's, plus discontinued combinations the catalog no longer offers
        -- all but ours disabled. ``desired`` compares the *enabled subset*."""
        assert len(live["variants"]) > len(wanted_variant_ids)
        assert len(live["variants"]) >= len(variants.variants)
        unavailable = [v for v in live["variants"] if not v["is_available"]]
        assert unavailable, (
            "expected the product to carry combinations the catalog no longer "
            "offers; if Printify stopped doing that, the enabled-subset rule "
            "above is still right but this note is stale"
        )

    def test_each_variant_carries_its_manufacturing_cost(
        self, live: dict[str, Any], wanted_variant_ids: list[int]
    ) -> None:
        """A *documented* per-variant cost, in cents. Not a replacement for
        ``newcmd/unofficial_variant_costs.py`` (A17) -- ``new`` needs the cost
        before a product exists -- but it is a cross-check for one, and the
        margin display's proper source once a product does exist."""
        for variant in live["variants"]:
            if variant["id"] in wanted_variant_ids:
                assert variant["cost"] > 0
                assert variant["price"] == PRICE

    def test_the_print_area_carries_our_placement(
        self, live: dict[str, Any], design: dict[str, Any]
    ) -> None:
        """Printify echoes the placement back with its own fields added --
        ``name``, ``src``, ``layerType``, a per-placement ``imageId``. A diff
        has to project down to what we sent, or every plan reports a change."""
        images = _front_images(live)
        assert len(images) == 1
        placed = images[0]
        assert placed["id"] == design["id"]
        assert (placed["x"], placed["y"], placed["scale"], placed["angle"]) == (0.5, 0.5, 1, 0)
        assert set(placed) > {"id", "x", "y", "scale", "angle"}

    def test_the_unused_placeholder_comes_back_empty_rather_than_absent(
        self, live: dict[str, Any]
    ) -> None:
        """We send ``front`` only; ``back`` appears with no images. Another
        difference between what was sent and what comes back."""
        positions = {
            placeholder["position"]
            for area in live["print_areas"]
            for placeholder in area["placeholders"]
        }
        assert "back" in positions

    def test_printify_generates_its_own_mockups(self, live: dict[str, Any]) -> None:
        """One set per enabled colour, several camera angles each, all flagged
        for publishing. These are the stock mockups the PRD exists to replace;
        knowing they arrive matters because the Etsy publish would otherwise
        use them."""
        assert live["images"]
        colours_covered = {
            variant_id for image in live["images"] for variant_id in image["variant_ids"]
        }
        assert colours_covered == set(_enabled(live))
        assert {image["position"] for image in live["images"]} >= {"front", "back"}

    def test_the_blueprints_default_tags_arrive_unasked(self, live: dict[str, Any]) -> None:
        """We sent no tags. Printify supplies the blueprint's, and they are
        what a publish would push -- which is what ``{tags: false}`` in the
        sync flags is for."""
        assert live["tags"]

    def test_no_response_anywhere_names_a_currency(
        self, live: dict[str, Any], printify_shop: dict[str, Any]
    ) -> None:
        """``price`` and ``cost`` are bare integers, and neither the product
        nor the shop says of what. The answer -- USD cents -- is only visible in
        Printify's web app, which is why it is written down in
        ``docs/api-findings.md`` rather than read off a response here. PRD 24
        requires every price to carry its currency, so the stage supplies the
        half the API withholds."""
        assert "currency" not in live
        assert "currency" not in printify_shop
        assert isinstance(live["variants"][0]["price"], int)
        assert isinstance(live["variants"][0]["cost"], int)


class TestWhatAnUpdateDoes:
    """``PUT /v1/shops/{shop}/products/{id}.json`` -- the apply path's other
    half, and the one with the surprises in it."""

    def test_a_body_carrying_one_field_leaves_the_others_alone(
        self, live: dict[str, Any], update, wanted_variant_ids: list[int]
    ) -> None:
        """So the stage may send just what changed, rather than re-sending a
        whole product and hoping."""
        before_title = live["title"]
        after = update(
            {
                "variants": [
                    {"id": v, "price": PRICE + 500, "is_enabled": True} for v in wanted_variant_ids
                ]
            }
        )
        try:
            assert after["title"] == before_title
            assert _front_images(after)[0]["id"] == _front_images(live)[0]["id"]
            assert {v["price"] for v in after["variants"] if v["is_enabled"]} == {PRICE + 500}
        finally:
            update(
                {
                    "variants": [
                        {"id": v, "price": PRICE, "is_enabled": True} for v in wanted_variant_ids
                    ]
                }
            )

    def test_omitting_a_variant_does_not_disable_it(
        self, update, wanted_variant_ids: list[int]
    ) -> None:
        """``variants`` merges by id. A listing that drops a colour and sends
        only the colours it kept would go on selling the dropped one -- so the
        stage has to send an explicit disable for every variant it is
        retiring, which means the lockfile has to remember what it enabled."""
        kept = wanted_variant_ids[:3]
        after = update({"variants": [{"id": v, "price": PRICE, "is_enabled": True} for v in kept]})
        assert _enabled(after) == wanted_variant_ids

    def test_an_explicit_disable_is_what_retires_a_variant(
        self, update, wanted_variant_ids: list[int]
    ) -> None:
        retired = wanted_variant_ids[-1]
        after = update({"variants": [{"id": retired, "price": PRICE, "is_enabled": False}]})
        try:
            assert retired not in _enabled(after)
            assert _enabled(after) == [v for v in wanted_variant_ids if v != retired]
        finally:
            update(
                {
                    "variants": [
                        {"id": v, "price": PRICE, "is_enabled": True} for v in wanted_variant_ids
                    ]
                }
            )

    def test_the_payload_that_created_the_product_is_rejected_as_an_update(
        self, update, create_spec: dict[str, Any]
    ) -> None:
        """``print_areas`` on an update must cover every variant the *product*
        has -- all 238 of them -- not the ones being sold. On create the two
        sets are the same, which is exactly why this is easy to miss."""
        error = update({"print_areas": create_spec["print_areas"]}, expect=400)
        assert error["code"] == 8251
        assert "print_areas" in error["errors"]["reason"]

    def test_covering_every_variant_is_what_an_update_wants(
        self, live: dict[str, Any], update, design: dict[str, Any]
    ) -> None:
        every = [v["id"] for v in live["variants"]]
        after = update(
            {
                "print_areas": [
                    {
                        "variant_ids": every,
                        "placeholders": [
                            {
                                "position": "front",
                                "images": [
                                    {
                                        "id": design["id"],
                                        "x": 0.5,
                                        "y": 0.4,
                                        "scale": 0.8,
                                        "angle": 0,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )
        try:
            placed = _front_images(after)[0]
            assert (placed["x"], placed["y"], placed["scale"]) == (0.5, 0.4, 0.8)
        finally:
            update({"print_areas": _whole_area(live, design)})

    def test_variant_groups_may_carry_different_artwork(
        self, live: dict[str, Any], printify_api: httpx.Client, update, design: dict[str, Any]
    ) -> None:
        """Several ``print_areas`` entries partitioning the variants, each with
        its own image. This is the API support PRD 30's on-light/on-dark
        artwork needs, and it was an open question until now."""
        light_ink = _upload(printify_api, "e2e-light-ink.png", _test_design((1100, 1320)))
        assert light_ink["id"] != design["id"]
        every = [v["id"] for v in live["variants"]]
        first_colour = sorted(
            v["id"] for v in live["variants"] if v["is_enabled"] and v["title"].startswith("Black")
        )
        rest = [v for v in every if v not in first_colour]
        after = update(
            {
                "print_areas": [
                    _area(first_colour, light_ink["id"]),
                    _area(rest, design["id"]),
                ]
            }
        )
        try:
            assert len(after["print_areas"]) == 2
            by_size = {len(a["variant_ids"]): a for a in after["print_areas"]}
            assert set(by_size) == {len(first_colour), len(rest)}
        finally:
            update({"print_areas": _whole_area(live, design)})

    def test_the_blueprint_cannot_be_changed_on_an_existing_product(
        self, live: dict[str, Any], update, reread
    ) -> None:
        """It answers 200 and ignores the field -- the quietest failure in this
        API. A profile that changes garment or printer means delete-and-
        recreate, and the stage has to say so rather than PUT and report
        success."""
        other = 6 if live["blueprint_id"] != 6 else 5
        update({"blueprint_id": other, "print_provider_id": live["print_provider_id"]})
        assert reread()["blueprint_id"] == live["blueprint_id"]

    def test_visible_is_writable_despite_being_documented_read_only(
        self, update, live: dict[str, Any]
    ) -> None:
        """The API reference marks ``visible`` read-only and the implementation
        plan concluded from that that draft-vs-live cannot be set through the
        API. It can be set; whether setting it makes an Etsy publish land as a
        draft is a separate question this shop cannot answer -- see
        ``docs/api-findings.md``."""
        assert live["visible"] is True
        after = update({"visible": False})
        try:
            assert after["visible"] is False
        finally:
            assert update({"visible": True})["visible"] is True


class TestPublishing:
    """``POST .../publish.json`` and the lock endpoints, on a shop with no
    sales channel connected. The Etsy half of this is Phase 3's to verify."""

    def test_publishing_without_a_sales_channel_is_a_named_error(
        self,
        disconnected: None,
        printify_api: httpx.Client,
        printify_shop: dict[str, Any],
        product: dict[str, Any],
    ) -> None:
        response = printify_api.post(
            f"/shops/{printify_shop['id']}/products/{product['id']}/publish.json",
            json={
                "title": False,
                "description": False,
                "images": False,
                "variants": True,
                "tags": False,
                "keyFeatures": False,
                "shipping_template": False,
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == 8254

    def test_a_failed_publish_leaves_the_product_unlocked(self, live: dict[str, Any]) -> None:
        """So the ``unlock`` path is not reachable this way. Whether a genuine
        in-flight publish locks the product, and whether
        ``publishing_failed.json`` clears it, needs a connected shop -- PRD
        risk 6 stays open."""
        assert live["is_locked"] is False

    def test_the_publish_budget_is_metered_separately(
        self,
        disconnected: None,
        printify_api: httpx.Client,
        printify_shop: dict[str, Any],
        product: dict[str, Any],
    ) -> None:
        """``X-RateLimit-Limit: 200`` on the publish endpoint against 600 on
        everything else -- the limiter's ``printify:publish`` bucket, confirmed
        rather than assumed."""
        response = printify_api.post(
            f"/shops/{printify_shop['id']}/products/{product['id']}/publish.json",
            json={"variants": True},
        )
        assert response.headers["x-ratelimit-limit"] == "200"


class TestErrorsAreDecodable:
    """Every failure below has the same shape, which is what the client's error
    decoding can rely on: ``{status, code, message, errors: {reason, code}}``."""

    def test_a_variant_outside_the_blueprint_is_a_400_naming_the_field(
        self,
        printify_api: httpx.Client,
        printify_shop: dict[str, Any],
        create_spec: dict[str, Any],
        design: dict[str, Any],
    ) -> None:
        spec = {
            **create_spec,
            "variants": [{"id": 1, "price": PRICE, "is_enabled": True}],
            "print_areas": [_area([1], design["id"])],
        }
        response = printify_api.post(f"/shops/{printify_shop['id']}/products.json", json=spec)
        assert response.status_code == 400
        body = response.json()
        assert body["status"] == "error"
        assert body["message"] == "Validation failed."
        assert body["errors"]["reason"]
        assert body["code"] == body["errors"]["code"]

    def test_a_missing_required_field_is_the_same_shape(
        self, printify_api: httpx.Client, printify_shop: dict[str, Any], garment: Blueprint
    ) -> None:
        response = printify_api.post(
            f"/shops/{printify_shop['id']}/products.json",
            json={"title": "no print areas", "blueprint_id": garment.id},
        )
        assert response.status_code == 400
        assert response.json()["errors"]["reason"].startswith("print_areas")


class TestNothingStopsUsCreatingTheSameProductTwice:
    def test_create_is_not_idempotent(
        self,
        printify_api: httpx.Client,
        printify_shop: dict[str, Any],
        product: dict[str, Any],
        create_spec: dict[str, Any],
    ) -> None:
        """There is no natural key and no conflict: an identical spec makes a
        second product. The lockfile's ``printify_product_id`` is the only
        thing standing between a re-run and a duplicate."""
        shop_id = printify_shop["id"]
        response = printify_api.post(f"/shops/{shop_id}/products.json", json=create_spec)
        assert response.status_code == 200
        duplicate = response.json()
        try:
            assert duplicate["id"] != product["id"]
        finally:
            assert (
                printify_api.delete(f"/shops/{shop_id}/products/{duplicate['id']}.json").status_code
                == 200
            )


class TestTheSecondRoundOfRecon:
    """Questions the first round did not have to ask, measured before the
    stage was written rather than after.

    Each of these was settled by a throwaway probe script and written into
    docs/api-findings.md; they live here so the offline suite's transcripts
    have something that re-takes them. A contract test can only prove we
    decode what Printify sent last time.
    """

    def test_the_shop_list_is_scoped_to_the_token(
        self, printify_api: httpx.Client, printify_shop: dict[str, Any]
    ) -> None:
        """Which is what makes `setup` able to discover the shop id rather
        than asking a human to find one (PRD 42)."""
        response = printify_api.get("/shops.json")
        assert response.status_code == 200

        shops = response.json()
        assert printify_shop["id"] in [shop["id"] for shop in shops]
        assert set(shops[0]) == {"id", "title", "sales_channel"}, (
            "three fields and nothing else -- no currency, no draft setting"
        )

    def test_a_sku_we_set_is_kept_verbatim(
        self, live: dict[str, Any], wanted_variant_ids: list[int]
    ) -> None:
        """`variants[].sku` is writable, despite nothing in the reference
        saying so. We decline to set one anyway (PRD 47) -- but the decision
        rests on this being a choice rather than a limit, so it is measured."""
        skus = {v["id"]: v.get("sku") for v in live["variants"] if v["is_enabled"]}
        assert all(sku for sku in skus.values()), "Printify generates one when we do not"

    def test_a_variant_entry_may_not_be_partial(
        self, update, wanted_variant_ids: list[int]
    ) -> None:
        """The measurement that shapes the retire path: switching a variant
        off still requires its price, so the lockfile has to remember what
        each enabled variant cost."""
        failure = update(
            {"variants": [{"id": wanted_variant_ids[0], "is_enabled": False}]}, expect=400
        )

        assert "price" in failure["errors"]["reason"]

    def test_the_product_list_is_a_paginator(
        self, printify_api: httpx.Client, printify_shop: dict[str, Any]
    ) -> None:
        response = printify_api.get(f"/shops/{printify_shop['id']}/products.json")
        assert response.status_code == 200

        body = response.json()
        assert {"current_page", "last_page", "per_page", "data", "total"} <= set(body)

    def test_the_product_list_honours_no_filter_at_all(
        self, printify_api: httpx.Client, printify_shop: dict[str, Any], product: dict[str, Any]
    ) -> None:
        """`title`, `search` and `sku` are each accepted with a 200 and
        ignored. This is why the duplicate guard is a walk rather than a
        query (PRD 48) -- if Printify ever adds a filter, this test is what
        notices, and the walk can become the query it should have been.
        """
        unfiltered = printify_api.get(f"/shops/{printify_shop['id']}/products.json").json()

        for params in ({"title": "no-such-title"}, {"search": "zzz"}, {"sku": "zzz"}):
            filtered = printify_api.get(
                f"/shops/{printify_shop['id']}/products.json", params=params
            ).json()
            assert filtered["total"] == unfiltered["total"], (
                f"params={params} filtered something -- the walk in PRD 48 can be "
                f"replaced by a query"
            )

    def test_limit_and_page_are_honoured_even_though_filters_are_not(
        self, printify_api: httpx.Client, printify_shop: dict[str, Any], product: dict[str, Any]
    ) -> None:
        """The walk has to page, so this is the part of the listing endpoint
        it genuinely depends on."""
        response = printify_api.get(
            f"/shops/{printify_shop['id']}/products.json", params={"limit": 1}
        )

        assert response.status_code == 200
        assert len(response.json()["data"]) <= 1


def _area(variant_ids: list[int], image_id: str) -> dict[str, Any]:
    return {
        "variant_ids": variant_ids,
        "placeholders": [
            {
                "position": "front",
                "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1.0, "angle": 0}],
            }
        ],
    }


def _whole_area(live: dict[str, Any], design: dict[str, Any]) -> list[dict[str, Any]]:
    """The restore payload: one print area over every variant the product has."""
    return [_area([v["id"] for v in live["variants"]], design["id"])]

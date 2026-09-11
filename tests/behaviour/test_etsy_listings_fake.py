"""Locks in the two measured behaviours `FakeEtsyListingClient` has to
reproduce or it blesses a broken media stage (phase-3-etsy.md, "Testing"):
`image_ids` as a full-replacement set that detaches omissions, and
`overwrite: true` replacing an image in place rather than colliding with it.
"""

from __future__ import annotations

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.models import VariationImageLink

SHOP_ID = 67961328
LISTING_ID = 4572550919


def _seeded() -> FakeEtsyListingClient:
    client = FakeEtsyListingClient()
    client.seed_listing(LISTING_ID, shop_id=SHOP_ID)
    return client


def test_a_new_upload_lands_at_its_rank() -> None:
    client = _seeded()

    image = client.upload_listing_image(
        SHOP_ID, LISTING_ID, file_name="black.png", contents=b"one", rank=1, alt_text="Black"
    )

    listing = client.get_listing(LISTING_ID, include_images=True)
    assert listing is not None
    assert [(i.listing_image_id, i.rank) for i in listing.images] == [(image.listing_image_id, 1)]


def test_image_ids_reorders_the_full_set() -> None:
    client = _seeded()
    a = client.upload_listing_image(SHOP_ID, LISTING_ID, file_name="a.png", contents=b"a", rank=1)
    b = client.upload_listing_image(SHOP_ID, LISTING_ID, file_name="b.png", contents=b"b", rank=2)

    client.update_listing(
        SHOP_ID, LISTING_ID, {"image_ids": [b.listing_image_id, a.listing_image_id]}
    )

    listing = client.get_listing(LISTING_ID, include_images=True)
    assert listing is not None
    assert [i.listing_image_id for i in listing.images] == [b.listing_image_id, a.listing_image_id]


def test_image_ids_detaches_whatever_it_omits() -> None:
    """A Printify mockup landing outside the manifest leaves the moment
    `image_ids` is next sent -- an id omitted from the list is detached, not
    merely left unordered."""
    client = _seeded()
    ours = client.upload_listing_image(
        SHOP_ID, LISTING_ID, file_name="ours.png", contents=b"ours", rank=1
    )
    client.upload_listing_image(
        SHOP_ID, LISTING_ID, file_name="printify-mockup.png", contents=b"mockup", rank=2
    )

    client.update_listing(SHOP_ID, LISTING_ID, {"image_ids": [ours.listing_image_id]})

    listing = client.get_listing(LISTING_ID, include_images=True)
    assert listing is not None
    assert [i.listing_image_id for i in listing.images] == [ours.listing_image_id]


def test_overwrite_replaces_in_place_leaving_count_and_neighbours_untouched() -> None:
    client = _seeded()
    first = client.upload_listing_image(
        SHOP_ID, LISTING_ID, file_name="a.png", contents=b"a", rank=1
    )
    second = client.upload_listing_image(
        SHOP_ID, LISTING_ID, file_name="b.png", contents=b"b", rank=2
    )

    replaced = client.upload_listing_image(
        SHOP_ID,
        LISTING_ID,
        file_name="a-v2.png",
        contents=b"a-v2",
        rank=1,
        overwrite=True,
        listing_image_id=first.listing_image_id,
    )

    listing = client.get_listing(LISTING_ID, include_images=True)
    assert listing is not None
    assert [i.listing_image_id for i in listing.images] == [
        replaced.listing_image_id,
        second.listing_image_id,
    ]
    assert replaced.listing_image_id != first.listing_image_id, "a new id, not the old one"


def test_a_replaced_images_variation_link_is_left_dangling() -> None:
    """Measured: replacing an image does not repoint or drop the swatch link
    that referenced it -- the read still answers with the stale id, which is
    what makes the media stage's live projection the only thing that can
    notice."""
    client = _seeded()
    first = client.upload_listing_image(
        SHOP_ID, LISTING_ID, file_name="a.png", contents=b"a", rank=1
    )
    client.update_variation_images(
        SHOP_ID,
        LISTING_ID,
        [VariationImageLink(property_id=513, value_id=1, image_id=first.listing_image_id)],
    )

    client.upload_listing_image(
        SHOP_ID,
        LISTING_ID,
        file_name="a-v2.png",
        contents=b"a-v2",
        rank=1,
        overwrite=True,
        listing_image_id=first.listing_image_id,
    )

    links = client.get_listing_variation_images(SHOP_ID, LISTING_ID)
    assert links[0].image_id == first.listing_image_id


def test_variation_images_round_trip_with_the_value_string() -> None:
    client = _seeded()

    client.update_variation_images(
        SHOP_ID,
        LISTING_ID,
        [VariationImageLink(property_id=513, value_id=50135267836, image_id=1, value="Black")],
    )

    links = client.get_listing_variation_images(SHOP_ID, LISTING_ID)
    assert (links[0].value_id, links[0].value) == (50135267836, "Black")


def test_an_empty_list_clears_the_links() -> None:
    client = _seeded()
    client.update_variation_images(
        SHOP_ID, LISTING_ID, [VariationImageLink(property_id=513, value_id=1, image_id=2)]
    )

    client.update_variation_images(SHOP_ID, LISTING_ID, [])

    assert client.get_listing_variation_images(SHOP_ID, LISTING_ID) == []


def test_shipping_profiles_and_production_partners_are_seeded() -> None:
    from etsy_listings.clients.etsy.models import ProductionPartner, ShippingProfile

    client = FakeEtsyListingClient(
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="NOK standard tee")],
        production_partners=[ProductionPartner(production_partner_id=2, partner_name="Partner")],
    )

    assert client.shipping_profiles(SHOP_ID)[0].title == "NOK standard tee"
    assert client.production_partners(SHOP_ID)[0].partner_name == "Partner"

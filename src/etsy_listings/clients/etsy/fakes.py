"""In-memory Etsy, for the behaviour layer (A4).

Behaviour tests drive this; contract tests drive the HTTP client through
`httpx`'s mock transport against transcripts. Asking either to do the other's
job is the mistake that split exists to prevent.
"""

from __future__ import annotations

from typing import Any

from etsy_listings.clients.etsy.models import (
    Inventory,
    Listing,
    ListingImage,
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    Shop,
    ShopSection,
    VariationImageLink,
)


class FakeEtsyShopClient:
    """Every read `setup` makes, answered from a dict.

    `find_shops` matches case-insensitively on the whole name rather than as a
    substring: what it stands in for is Etsy's own search, and the caller's
    job is to decide whether a result really is the shop it asked about.
    """

    def __init__(
        self,
        shops: list[Shop] | None = None,
        *,
        owned: Shop | None = None,
        sections: list[ShopSection] | None = None,
        policies: list[ReturnPolicy] | None = None,
    ) -> None:
        self._shops = list(shops or [])
        self._owned = owned
        self._sections = list(sections or [])
        self._policies = list(policies or [])
        self.searched: list[str] = []
        self.owner_lookups: list[int] = []
        self.section_calls = 0
        self.return_policy_calls = 0

    def find_shops(self, name: str) -> list[Shop]:
        self.searched.append(name)
        return [shop for shop in self._shops if shop.shop_name.lower() == name.lower()]

    def shop_by_owner(self, user_id: int) -> Shop | None:
        self.owner_lookups.append(user_id)
        return self._owned

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        self.section_calls += 1
        return list(self._sections)

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        self.return_policy_calls += 1
        return list(self._policies)


class FakeEtsyListingClient:
    """Models the two measured API quirks a tidy fake would hide: `image_ids`
    as a full-replacement set that detaches whatever it omits, and
    `overwrite: true` replacing an image in place -- a new id at the same
    rank, everything else untouched -- rather than colliding with what was
    there (phase-3-etsy.md decision 5).
    """

    def __init__(
        self,
        *,
        shipping_profiles: list[ShippingProfile] | None = None,
        production_partners: list[ProductionPartner] | None = None,
        sections: list[ShopSection] | None = None,
        policies: list[ReturnPolicy] | None = None,
    ) -> None:
        self._listings: dict[int, Listing] = {}
        self._images: dict[int, list[ListingImage]] = {}
        self._inventory: dict[int, Inventory] = {}
        self._variation_images: dict[int, list[VariationImageLink]] = {}
        self._shipping_profiles = list(shipping_profiles or [])
        self._production_partners = list(production_partners or [])
        self._sections = list(sections or [])
        self._policies = list(policies or [])
        self._next_image_id = 0
        self.updated: list[dict[str, Any]] = []
        self.uploads: list[bytes] = []
        """Every upload's bytes, in call order -- what a test checks to prove
        a re-run did *not* resend an image whose content did not change."""
        self.shipping_profile_calls = 0
        self.production_partner_calls = 0
        self.section_calls = 0
        self.return_policy_calls = 0

    def seed_listing(self, listing_id: int, *, shop_id: int | None = None, **fields: Any) -> None:
        self._listings[listing_id] = Listing(listing_id=listing_id, shop_id=shop_id, **fields)
        self._images.setdefault(listing_id, [])

    def seed_inventory(self, listing_id: int, inventory: Inventory) -> None:
        self._inventory[listing_id] = inventory

    # -------------------------------------------------------------- reads

    def get_listing(self, listing_id: int, *, include_images: bool = False) -> Listing | None:
        listing = self._listings.get(listing_id)
        if listing is None:
            return None
        images = tuple(self._images.get(listing_id, [])) if include_images else ()
        return listing.model_copy(update={"images": images})

    def get_listing_inventory(self, listing_id: int) -> Inventory:
        return self._inventory.get(listing_id, Inventory())

    def get_listing_variation_images(self, listing_id: int) -> list[VariationImageLink]:
        return list(self._variation_images.get(listing_id, []))

    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]:
        self.shipping_profile_calls += 1
        return list(self._shipping_profiles)

    def production_partners(self, shop_id: int) -> list[ProductionPartner]:
        self.production_partner_calls += 1
        return list(self._production_partners)

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        self.section_calls += 1
        return list(self._sections)

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        self.return_policy_calls += 1
        return list(self._policies)

    # ------------------------------------------------------------- writes

    def update_listing(self, shop_id: int, listing_id: int, patch: dict[str, Any]) -> Listing:
        self.updated.append(dict(patch))
        image_ids = patch.get("image_ids")
        if image_ids is not None:
            by_id = {image.listing_image_id: image for image in self._images.get(listing_id, [])}
            self._images[listing_id] = [by_id[i] for i in image_ids if i in by_id]
        fields = {
            key: value
            for key, value in patch.items()
            if key != "image_ids" and key in Listing.model_fields
        }
        self._listings[listing_id] = self._listings[listing_id].model_copy(update=fields)
        return self._listings[listing_id].model_copy(update={"images": ()})

    def upload_listing_image(
        self,
        shop_id: int,
        listing_id: int,
        *,
        file_name: str,
        contents: bytes,
        rank: int,
        alt_text: str = "",
        overwrite: bool = False,
        listing_image_id: int | None = None,
    ) -> ListingImage:
        self.uploads.append(contents)
        self._next_image_id += 1
        image = ListingImage(listing_image_id=self._next_image_id, rank=rank, alt_text=alt_text)
        images = self._images.setdefault(listing_id, [])
        if overwrite and listing_image_id is not None:
            for index, existing in enumerate(images):
                if existing.listing_image_id == listing_image_id:
                    images[index] = image
                    return image
        images.append(image)
        return image

    def update_variation_images(
        self, shop_id: int, listing_id: int, links: list[VariationImageLink]
    ) -> None:
        self._variation_images[listing_id] = list(links)

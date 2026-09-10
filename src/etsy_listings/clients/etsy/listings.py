"""The Etsy listing surface Phase 3's stages write through: `publish`'s poll
target, `etsy_listing`'s single PATCH, and `etsy_media`'s upload/reorder/
variation-image calls.

Built against
[docs/printify-etsy-integration.md](../../../../docs/printify-etsy-integration.md)'s
Phase 3 recon rather than the API reference alone, because two of its
findings make the obvious implementation wrong:

- **`image_ids` has two encodings, and only one is safe.** Sent as one
  comma-separated value it reorders and detaches correctly; sent as repeated
  form keys it answers `200` and destroys every image but one. Both look
  identical from the response, so :meth:`update_listing` always joins a list
  under that key into one string rather than letting `httpx` serialise it.
- **The shop-scoped single-listing path 404s on `GET`.** `getListing` reads
  the unscoped path (`/v3/application/listings/{id}`); the shop-scoped one is
  for `PATCH`/`DELETE` only.

Separate from :class:`~etsy_listings.clients.etsy.shops.EtsyShopClient` for
the reason A22 gives: authority is a property of the type, so a caller
resolving `setup`'s four unscoped reads cannot reach `updateListing` however
much transport plumbing the two share. `shop_sections` and `return_policies`
exist on **both** protocols despite being unscoped calls, because the two
serve different lifecycles rather than different authority: `setup` needs
them before a token exists at all (`EtsyShopClient`), while
`EtsyShopCatalog` needs them from the one client `RunContext` actually
carries once a run is signed in -- adding a second client field to
`RunContext` just to reach two calls its `EtsyListingClient` could make
over the same transport would be the wrong seam to add.
"""

from __future__ import annotations

from typing import Any, Protocol

from etsy_listings.clients.etsy.models import (
    Inventory,
    Listing,
    ListingImage,
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    ShopSection,
    VariationImageLink,
)
from etsy_listings.clients.etsy.transport import HTTP_NOT_FOUND, EtsyApiError, Transport


class EtsyListingClient(Protocol):
    """Everything Phase 3's stages need from a signed-in Etsy connection:
    `listings_w` for every write, plus the `shops_r` reads that resolve a
    shipping profile or production partner by name (decision 2)."""

    def get_listing(self, listing_id: int, *, include_images: bool = False) -> Listing | None: ...

    def update_listing(self, shop_id: int, listing_id: int, patch: dict[str, Any]) -> Listing: ...

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
    ) -> ListingImage: ...

    def get_listing_inventory(self, listing_id: int) -> Inventory: ...

    def update_variation_images(
        self, shop_id: int, listing_id: int, links: list[VariationImageLink]
    ) -> None: ...

    def get_listing_variation_images(self, listing_id: int) -> list[VariationImageLink]: ...

    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]: ...

    def production_partners(self, shop_id: int) -> list[ProductionPartner]: ...

    def shop_sections(self, shop_id: int) -> list[ShopSection]: ...

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]: ...


class HttpEtsyListingClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    # ------------------------------------------------------------- reads

    def get_listing(self, listing_id: int, *, include_images: bool = False) -> Listing | None:
        params = {"includes": "Images"} if include_images else None
        try:
            response = self._transport.get(f"/v3/application/listings/{listing_id}", params=params)
        except EtsyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND:
                return None
            raise
        return Listing.model_validate(response.json())

    def get_listing_inventory(self, listing_id: int) -> Inventory:
        response = self._transport.get(f"/v3/application/listings/{listing_id}/inventory")
        return Inventory.model_validate(response.json())

    def get_listing_variation_images(self, listing_id: int) -> list[VariationImageLink]:
        response = self._transport.get(f"/v3/application/listings/{listing_id}/variation-images")
        return [VariationImageLink.model_validate(row) for row in _results(response.json())]

    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/shipping-profiles")
        return [ShippingProfile.model_validate(row) for row in _results(response.json())]

    def production_partners(self, shop_id: int) -> list[ProductionPartner]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/production-partners")
        return [ProductionPartner.model_validate(row) for row in _results(response.json())]

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/sections")
        return [ShopSection.model_validate(row) for row in _results(response.json())]

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/policies/return")
        return [ReturnPolicy.model_validate(row) for row in _results(response.json())]

    # ------------------------------------------------------------- writes

    def update_listing(self, shop_id: int, listing_id: int, patch: dict[str, Any]) -> Listing:
        body = dict(patch)
        if isinstance(body.get("image_ids"), (list, tuple)):
            # The sharp edge: comma-separated reorders and detaches; repeated
            # keys answer 200 and destroy every image but one. Only a single
            # string value in a JSON body can never be re-encoded that way.
            body["image_ids"] = ",".join(str(image_id) for image_id in body["image_ids"])
        response = self._transport.patch(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}", json=body
        )
        return Listing.model_validate(response.json())

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
        """Upload at `rank`, with `alt_text` -- there is no image-update
        endpoint, so alt text is only ever set here (PRD 57).

        `overwrite` replaces the image already at that rank in place, keeping
        its count and neighbouring ranks untouched and minting a new id
        rather than colliding with what was there (measured). It needs
        `listing_image_id` naming what to replace.
        """
        data: dict[str, str] = {"rank": str(rank), "alt_text": alt_text}
        if overwrite:
            data["overwrite"] = "true"
        if listing_image_id is not None:
            data["listing_image_id"] = str(listing_image_id)
        response = self._transport.post(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}/images",
            data=data,
            files={"image": (file_name, contents)},
        )
        return ListingImage.model_validate(response.json())

    def update_variation_images(
        self, shop_id: int, listing_id: int, links: list[VariationImageLink]
    ) -> None:
        """Overwrite every swatch link on the listing (PRD 56). An empty list
        is a write that clears them, not a no-op -- measured."""
        body = {
            "variation_images": [
                {
                    "property_id": link.property_id,
                    "value_id": link.value_id,
                    "image_id": link.image_id,
                }
                for link in links
            ]
        }
        self._transport.post(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}/variation-images", json=body
        )


def _results(body: Any) -> list[Any]:
    """Etsy's list envelope is always ``{count, results}``."""
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        return list(body["results"])
    return []

"""The Etsy responses this tool reads, narrowed to the fields it uses.

Etsy's `Shop` carries forty-seven fields, most of them about a storefront's
presentation. Modelling all of them would make every one of them look load
bearing, and would turn a field Etsy renames into a validation error in a
workspace that never touched it. So: the few we act on, and `extra="ignore"`
for the rest.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class Shop(BaseModel):
    """An Etsy shop, as `findShops` and `getShopByOwnerUserId` return it.

    `currency_code` is the reason this model exists beyond the id: it is the
    shop's own currency, and reading it is what stops a workspace being
    configured in one currency while the shop sells in another (PRD 51).
    """

    model_config = ConfigDict(extra="ignore")

    shop_id: int
    shop_name: str
    currency_code: str | None = None
    user_id: int | None = None
    url: str | None = None


class ShopSection(BaseModel):
    """A section a listing can be filed under (`etsy.shop_section_id`)."""

    model_config = ConfigDict(extra="ignore")

    shop_section_id: int
    title: str
    active_listing_count: int | None = None


class ReturnPolicy(BaseModel):
    """A listing-level return policy (`etsy.return_policy_id`).

    Etsy gives these no title, so the only way to tell two apart is the terms
    themselves -- which is why all three fields are carried rather than the id
    alone: a picker offering "1122334" and "1122335" would be a coin toss.
    """

    model_config = ConfigDict(extra="ignore")

    return_policy_id: int
    accepts_returns: bool | None = None
    accepts_exchanges: bool | None = None
    return_deadline: int | None = None

    def describe(self) -> str:
        if self.accepts_returns is None and self.accepts_exchanges is None:
            return f"policy {self.return_policy_id}"
        accepted = [
            name
            for name, allowed in (
                ("returns", self.accepts_returns),
                ("exchanges", self.accepts_exchanges),
            )
            if allowed
        ]
        if not accepted:
            return "no returns or exchanges"
        within = f" within {self.return_deadline} days" if self.return_deadline else ""
        return f"{' and '.join(accepted)}{within}"


class ShippingProfile(BaseModel):
    """A shipping profile (`etsy.shipping_profile_id`), addressed by title
    (PRD 54) -- Etsy gives these a title, unlike a return policy."""

    model_config = ConfigDict(extra="ignore")

    shipping_profile_id: int
    title: str
    origin_country_iso: str | None = None
    is_deleted: bool = False


class ProductionPartner(BaseModel):
    """A fulfilment relationship the shop has declared (PRD 52).

    Etsy gives it a name and a location but not, notably, a link to
    `profile.print_provider` -- the two describe different things (decision
    3's resolution ladder). Read the same way whether it came from
    `getShopProductionPartners` or nested in a listing's own
    `production_partners`.
    """

    model_config = ConfigDict(extra="ignore")

    production_partner_id: int
    partner_name: str | None = None
    location: str | None = None


class ListingImage(BaseModel):
    """One image on a listing, as `getListing?includes=Images` and
    `uploadListingImage` both return it."""

    model_config = ConfigDict(extra="ignore")

    listing_image_id: int
    rank: int | None = None
    alt_text: str | None = None
    url_570xN: str | None = None
    """A thumbnail up to 570px wide, variable height -- Etsy's own field name
    (the API's `ListingImage` schema). What the deploy review's "On Etsy now"
    column shows (A30): the URL a draft or a hand-uploaded image already has,
    with no local render to fall back on for either. Absent unless the read
    asked for images (`include_images=True`), same as `rank`."""


class ListingVideo(BaseModel):
    """One video on a listing, as `getListing?includes=Videos`,
    `uploadListingVideo` and a re-attach by id all return it (decision 9).

    `video_state` is carried because an `inactive` video stays in every list
    Etsy returns -- a caller that took presence for "on the listing" would
    miss one that no longer shows. The dimensions are Etsy's transcode, not
    the file's: a 1440 px upload came back 1440, a 540 px one 540, and
    neither says where in the gallery the video sits; nothing does.
    """

    model_config = ConfigDict(extra="ignore")

    video_id: int
    video_state: str | None = None
    width: int | None = None
    height: int | None = None
    video_url: str | None = None
    thumbnail_url: str | None = None


class VariationImageLink(BaseModel):
    """One `(property, value) -> image` swatch binding (PRD 56).

    `value` is present on a read (`getListingVariationImages` returns the
    value string alongside each id, which is what makes the reverse
    projection free) and absent on a write -- Etsy only wants the ids sent.
    """

    model_config = ConfigDict(extra="ignore")

    property_id: int
    value_id: int
    image_id: int
    value: str | None = None


class InventoryPropertyValue(BaseModel):
    """One property on one inventory product-combination -- e.g. this
    combination's colour, or its size. `property_name` is the *blueprint's*
    option name (PRD 3, "Comfort Colors® Colors" rather than "Color"), which
    is why the colour property is identified by matching `values` against the
    listing's own colours rather than by name or id (decision 6)."""

    model_config = ConfigDict(extra="ignore")

    property_id: int
    property_name: str | None = None
    value_ids: tuple[int, ...] = ()
    values: tuple[str, ...] = ()


class InventoryOffering(BaseModel):
    model_config = ConfigDict(extra="ignore")

    offering_id: int | None = None
    quantity: int | None = None
    is_enabled: bool | None = None


class InventoryProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_id: int | None = None
    sku: str | None = None
    property_values: tuple[InventoryPropertyValue, ...] = ()
    offerings: tuple[InventoryOffering, ...] = ()


class Inventory(BaseModel):
    """`getListingInventory`'s response: Printify's variant matrix as Etsy
    materialised it, including the disabled cross-product cells Etsy adds to
    keep the grid rectangular (PRD 55 -- read here, never written)."""

    model_config = ConfigDict(extra="ignore")

    products: tuple[InventoryProduct, ...] = ()


class Listing(BaseModel):
    """`getListing`'s response, narrowed to what the stages compare against
    `applied` (the Etsy write surface table in phase-3-etsy.md).

    Read only through `GET /v3/application/listings/{id}` -- the *unscoped*
    path. The shop-scoped one exists for `PATCH`/`DELETE` and 404s on `GET`,
    which cost the probe a false "our copy was overwritten" verdict.
    """

    model_config = ConfigDict(extra="ignore")

    listing_id: int
    shop_id: int | None = None
    state: str | None = None
    title: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()
    shop_section_id: int | None = None
    shipping_profile_id: int | None = None
    return_policy_id: int | None = None
    who_made: str | None = None
    when_made: str | None = None
    is_supply: bool | None = None
    should_auto_renew: bool | None = None
    production_partners: tuple[ProductionPartner, ...] = ()
    readiness_state_id: int | None = None
    processing_min: int | None = None
    processing_max: int | None = None
    images: tuple[ListingImage, ...] = ()
    videos: tuple[ListingVideo, ...] = ()
    """Newest *upload* first, inactive ones included (measured). An ordering
    of the response, not of the gallery -- which the API never reports."""

    @field_validator("images", "videos", mode="before")
    @classmethod
    def _null_images_is_none_requested(cls, value: object) -> object:
        """``getListing`` sends ``images: null``, not an omitted key or ``[]``,
        when called without ``includes=Images`` (measured) -- the default
        every ``read_live()`` but ``etsy_media``'s asks for. The field default
        only covers a *missing* key, so without this a plain re-plan of an
        existing listing fails validation on every run. ``videos`` has the
        same shape without ``includes=Videos`` (PRD 71)."""
        return () if value is None else value

"""The Etsy responses this tool reads, narrowed to the fields it uses;
the rest are ignored so an Etsy rename never fails validation."""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator, model_validator


class Shop(BaseModel):
    """An Etsy shop, as `findShops` and `getShopByOwnerUserId` return it."""

    model_config = ConfigDict(extra="ignore")

    shop_id: int
    shop_name: str
    currency_code: str | None = None
    user_id: int | None = None
    url: str | None = None


class ShopSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shop_section_id: int
    title: str
    active_listing_count: int | None = None


class ReturnPolicy(BaseModel):
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
    model_config = ConfigDict(extra="ignore")

    shipping_profile_id: int
    title: str
    origin_country_iso: str | None = None
    is_deleted: bool = False


class ProductionPartner(BaseModel):
    model_config = ConfigDict(extra="ignore")

    production_partner_id: int
    partner_name: str | None = None
    location: str | None = None


class ListingImage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    listing_image_id: int
    rank: int | None = None
    alt_text: str | None = None
    url_570xN: str | None = None  # noqa: N815 -- Etsy's ListingImage field name
    """A thumbnail up to 570px wide, variable height -- Etsy's own field name
    (the API's `ListingImage` schema). What the deploy review's "On Etsy now"
    column shows: the URL a draft or a hand-uploaded image already has,
    with no local render to fall back on for either. Absent unless the read
    asked for images (`include_images=True`), same as `rank`."""


class ListingVideo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    video_id: int
    video_state: str | None = None
    width: int | None = None
    height: int | None = None
    video_url: str | None = None
    thumbnail_url: str | None = None


class VariationImageLink(BaseModel):
    model_config = ConfigDict(extra="ignore")

    property_id: int
    value_id: int
    image_id: int
    value: str | None = None


class InventoryPropertyValue(BaseModel):
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
    model_config = ConfigDict(extra="ignore")

    products: tuple[InventoryProduct, ...] = ()


def _unescape_copy(value: dict[str, Any]) -> dict[str, Any]:
    value = dict(value)
    for key in ("title", "description"):
        if isinstance(value.get(key), str):
            value[key] = html.unescape(value[key])
    if isinstance(value.get("tags"), list):
        value["tags"] = [html.unescape(t) if isinstance(t, str) else t for t in value["tags"]]
    return value


class Listing(BaseModel):
    """`getListing`'s response, narrowed to what the stages compare against
    `applied`. Etsy sends text HTML-escaped (measured); it is unescaped here, once.
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

    @model_validator(mode="before")
    @classmethod
    def _decode(cls, value: object) -> object:
        return _unescape_copy(value) if isinstance(value, dict) else value

    @field_validator("images", "videos", mode="before")
    @classmethod
    def _null_images_is_none_requested(cls, value: object) -> object:
        """Etsy sends ``null`` for media not in ``includes`` (measured)."""
        return () if value is None else value


# ------------------------------------------------------------------ market


def _drop_nulls(value: object) -> object:
    """Etsy sends ``null`` and omits a key interchangeably; dropping nulls
    lets the field defaults answer both."""
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if item is not None}
    return value


ALREADY_DECODED: Mapping[str, bool] = {"already_decoded": True}
"""Validation context for a market model read back from this tool's own
cache: its text was unescaped when Etsy's answer was first decoded, and a
second pass would turn a seller's literal ``&amp;`` into ``&``."""


class MarketCandidate(BaseModel):
    """Another seller's active listing, as `findAllListingsActive` returns
    it. Every field but the ids is optional, since Etsy rows are sparse, and
    text arrives HTML-escaped (measured) and is unescaped here, once.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    listing_id: int
    shop_id: int
    title: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    num_favorers: int = 0
    views: int = 0
    original_creation_timestamp: int | None = None
    """Epoch seconds. The listing's *first* creation -- a renewal resets
    `creation_timestamp` but not this, and a listing's age is what turns
    favourites and views into per-day rates. Falls back to
    `creation_timestamp` when Etsy leaves it out."""
    url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _decode(cls, value: Any, info: ValidationInfo) -> Any:
        value = _drop_nulls(value)
        if not isinstance(value, dict) or (info.context or {}).get("already_decoded"):
            return value
        if "original_creation_timestamp" not in value and "creation_timestamp" in value:
            value["original_creation_timestamp"] = value["creation_timestamp"]
        return _unescape_copy(value)


class ShopStats(BaseModel):
    """The selling shop's signals, from the batch call's ``includes=Shop``.
    ``review_average`` is ``None`` for a shop with no reviews this year."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    shop_name: str = ""
    transaction_sold_count: int = 0
    review_average: float | None = None
    review_count: int = 0

    @model_validator(mode="before")
    @classmethod
    def _decode(cls, value: Any) -> Any:
        return _drop_nulls(value)


class MarketListing(MarketCandidate):
    shop: ShopStats | None = None
    thumbnail_url: str | None = None
    """``url_170x135`` of the listing's first image by rank -- Etsy's
    170px thumbnail, the size the panel's 40px tile needs at any density."""

    @model_validator(mode="before")
    @classmethod
    def _thumbnail(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "thumbnail_url" in value:
            return value
        images = [image for image in value.get("images") or () if isinstance(image, dict)]
        if not images:
            return value
        first = min(images, key=lambda image: image.get("rank") or 0)
        return {**value, "thumbnail_url": first.get("url_170x135")}

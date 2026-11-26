from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error, parse_yaml


class MissingDefaultError(ValueError):
    def __init__(self, field_path: str, needed_to: str, how_to_find: str) -> None:
        self.field_path = field_path
        super().__init__(
            f"shop.yaml: {field_path} is not set, and is required to {needed_to}. {how_to_find}"
        )


class PrintifyDefaults(BaseModel):
    """Which Printify shop this workspace creates products in.

    Optional at load, like the Etsy ids: a workspace that only renders mockups
    has no use for it, and a product call that needs it raises
    :class:`MissingDefaultError` then.
    """

    model_config = ConfigDict(extra="forbid")

    shop_name: str | None = None
    """What the shop is called in Printify, stored beside the id.

    Not a resolution key -- `setup` selects the shop and stores its id, and
    Printify's titles are whatever the owner typed. It is here so that the
    stored id is *checkable*: "28819281" tells a reader nothing about whether
    this workspace points at the right place."""

    shop_id: int | None = None
    preferred_print_provider: str | None = None
    """By name, not id. Preselected in `new` when it offers the chosen
    garment. Under `printify:` because it names a Printify entity."""

    def require_shop_id(self) -> int:
        if self.shop_id is None:
            raise MissingDefaultError(
                "printify.shop_id",
                "create or update a Printify product",
                "Run `etsy-listings setup`: it reads the shops your token can "
                "reach from Printify and writes the id here, so there is no id "
                "to go and find by hand.",
            )
        return self.shop_id


class EtsyReturnPolicyDefaults(BaseModel):
    """Etsy return policies have no title: `getShopReturnPolicies` is matched
    on these three terms exactly."""

    model_config = ConfigDict(extra="forbid")

    accepts_returns: bool
    accepts_exchanges: bool
    within_days: int | None = None


class EtsyListingDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    who_made: str = "someone_else"
    when_made: str = "made_to_order"
    is_supply: bool = False
    renewal: Literal["manual", "auto"] = "manual"
    shipping_profile: str | None = None
    """By name, not id -- resolved against the shop's shipping
    profiles at plan time (`EtsyShopCatalog`), since a stale id would fail
    the whole `updateListing` PATCH."""
    return_policy: EtsyReturnPolicyDefaults | None = None
    production_partner: str | None = None
    """By name; omit when the shop has exactly one, as most shops can."""


class EtsyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    """The shop's own currency, read from Etsy by `setup`.

    Under `etsy:` because it describes the Etsy shop, and read rather than
    typed because a workspace configured in one currency while the shop sells
    in another is a disagreement nothing surfaces until a price lands wrong.
    ADR-0006 is unchanged: it remains the only currency a price may be written
    in."""

    shop_name: str | None = None
    """The shop's name on Etsy -- the human-readable half of its identity, and
    what `findShops` resolves the id from."""

    shop_id: int | None = None

    listing_defaults: EtsyListingDefaults = EtsyListingDefaults()
    """What a listing inherits. Everything outside this block identifies or
    configures the shop -- a distinction worth drawing because the two have
    different failure modes: a wrong `shop_id` means nothing works, while a
    wrong default means every listing is quietly slightly wrong.

    No shop-wide section: which part of the shop a listing belongs in is
    ``listing.yaml``'s ``etsy.section``.
    """

    def require_shop_id(self) -> int:
        if self.shop_id is None:
            raise MissingDefaultError(
                "etsy.shop_id",
                "read or patch a listing on Etsy",
                "It is the number in your Etsy shop manager's URL; Phase 3's "
                "`auth` flow can also read it back from the Etsy API.",
            )
        return self.shop_id


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    etsy: EtsyDefaults
    printify: PrintifyDefaults = PrintifyDefaults()

    @classmethod
    def load(cls, path: Path) -> Defaults:
        if not path.is_file():
            raise ConfigLoadError(path, "file not found")
        raw = parse_yaml(path, path.read_text(encoding="utf-8")) or {}
        try:
            return cls.from_document(path, raw)
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

    @classmethod
    def from_document(cls, path: Path, raw: object) -> Defaults:
        del path
        return cls.model_validate(raw)

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
    """Which Printify shop this workspace creates products in: optional, as a workspace that only
    renders mockups needs none."""

    model_config = ConfigDict(extra="forbid")

    shop_name: str | None = None
    """Stored beside the id so a reader can check it; never a resolution key."""

    shop_id: int | None = None
    preferred_print_provider: str | None = None
    """By name, not id; preselected in `new` when it offers the chosen garment."""

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
    """The shop's own currency, read from Etsy by `setup` so the workspace cannot disagree with the
    shop; the only currency a price may be written in (ADR-0006)."""

    shop_name: str | None = None
    """The shop's name on Etsy -- the human-readable half of its identity, and
    what `findShops` resolves the id from."""

    shop_id: int | None = None

    listing_defaults: EtsyListingDefaults = EtsyListingDefaults()
    """What a listing inherits; the rest of this block identifies the shop. The section is per
    listing (``listing.yaml``'s ``etsy.section``)."""

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

"""``shop.yaml``: shop-wide configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.config.errors import ConfigLoadError, format_validation_error


class MissingDefaultError(ValueError):
    """A ``shop.yaml`` field that only some phases need, asked for by a
    phase that needs it.

    Raised at the point of use rather than at load, so a workspace can be set
    up and used for everything that doesn't need the field yet. The message
    carries the dotted path, because "shop_id" alone is ambiguous now that
    both ``etsy`` and ``printify`` have one.
    """

    def __init__(self, field_path: str, needed_to: str, how_to_find: str) -> None:
        self.field_path = field_path
        super().__init__(
            f"shop.yaml: {field_path} is not set, and is required to {needed_to}. {how_to_find}"
        )


class PrintifyDefaults(BaseModel):
    """Which Printify shop this workspace creates products in (PRD 42).

    Every product call is shop-scoped -- ``/v1/shops/{shop}/products.json`` --
    so nothing in Phase 2 can run without it. Optional at load anyway, for the
    same reason the Etsy ids are: a workspace that only renders mockups has no
    use for it, and every workspace written before Phase 2 has no ``printify:``
    block at all.
    """

    model_config = ConfigDict(extra="forbid")

    shop_name: str | None = None
    """What the shop is called in Printify, stored beside the id (PRD 51).

    Not a resolution key -- `setup` selects the shop and stores its id, and
    Printify's titles are whatever the owner typed. It is here so that the
    stored id is *checkable*: "28819281" tells a reader nothing about whether
    this workspace points at the right place."""

    shop_id: int | None = None
    preferred_print_provider: str | None = None
    """By name, not id. Preselected in `new` when it offers the chosen
    garment. Under `printify:` because it names a Printify entity (PRD 51)."""

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
    """A return policy's identity, since Etsy gives the resource no title
    (PRD 59). The three terms *are* the identity -- `getShopReturnPolicies`
    is matched on them exactly, and `describe()` (models.py) is what a plan
    renders instead of a bare id."""

    model_config = ConfigDict(extra="forbid")

    accepts_returns: bool
    accepts_exchanges: bool
    within_days: int | None = None


class EtsyListingDefaults(BaseModel):
    """Every field a listing inherits, and nothing that identifies the shop
    (phase-3-etsy.md, "Config, after this phase"). Overridable per listing in
    `listing.yaml`'s own `etsy:` block.

    `who_made` defaults to `someone_else` (PRD 52): the shirt genuinely was
    made by another company, and that declaration requires a production
    partner attached to the *listing* -- checked at plan time (decision 3),
    not here, since resolving a name to a partner needs the shop's live list.
    """

    model_config = ConfigDict(extra="forbid")

    who_made: str = "someone_else"
    when_made: str = "made_to_order"
    is_supply: bool = False
    renewal: Literal["manual", "auto"] = "manual"
    shipping_profile: str | None = None
    """By name, not id (PRD 54) -- resolved against the shop's shipping
    profiles at plan time (`EtsyShopCatalog`), since a stale id would fail
    the whole `updateListing` PATCH."""
    return_policy: EtsyReturnPolicyDefaults | None = None
    production_partner: str | None = None
    """By name; omit when the shop has exactly one (decision 3's resolution
    ladder) -- most shops never need to set this."""


class EtsyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    """The shop's own currency, read from Etsy by `setup` (PRD 51).

    Under `etsy:` because it describes the Etsy shop, and read rather than
    typed because a workspace configured in one currency while the shop sells
    in another is a disagreement nothing surfaces until a price lands wrong.
    PRD 24 is unchanged: it remains the only currency a price may be written
    in."""

    shop_name: str | None = None
    """The shop's name on Etsy -- the human-readable half of its identity, and
    what `findShops` resolves the id from (PRD 51)."""

    # Deferrable, like `printify.shop_id`: it normally comes back *from* the
    # Etsy API, so demanding it at load time made a workspace unusable before
    # an Etsy shop exists to discover it from.
    shop_id: int | None = None

    listing_defaults: EtsyListingDefaults = EtsyListingDefaults()
    """What a listing inherits. Everything outside this block identifies or
    configures the shop -- a distinction worth drawing because the two have
    different failure modes: a wrong `shop_id` means nothing works, while a
    wrong default means every listing is quietly slightly wrong.

    No shop-wide section, unlike Phase 2's `shop_section_id`: which part of
    the shop a listing belongs in is a fact about that listing, not the shop
    (`listing.yaml`'s `etsy.section`), and a shop-wide default would be right
    for the first listing and wrong from the second onwards.
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


MOVED_KEYS = {
    "currency": "etsy.currency",
    "preferred_print_provider": "printify.preferred_print_provider",
}
"""Where two top-level keys went (PRD 51).

`extra="forbid"` would report them as "extra inputs are not permitted", which
is true and useless: the value is not extra, it is one line further down the
file. A workspace written before the move is exactly the one whose owner needs
to be told where to put it."""


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    etsy: EtsyDefaults
    printify: PrintifyDefaults = PrintifyDefaults()

    @classmethod
    def load(cls, path: Path) -> Defaults:
        if not path.is_file():
            raise ConfigLoadError(path, "file not found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            _refuse_moved_keys(path, raw)
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc


def _refuse_moved_keys(path: Path, raw: dict[str, object]) -> None:
    found = [(key, moved_to) for key, moved_to in MOVED_KEYS.items() if key in raw]
    if not found:
        return
    moves = "\n".join(f"  {key}: -> {moved_to}:" for key, moved_to in found)
    raise ConfigLoadError(
        path,
        "these keys moved under the service that owns them (PRD 51):\n"
        f"{moves}\n"
        "  Move them by hand, or re-run `etsy-listings setup`, which rewrites "
        "the file in the current shape.",
    )

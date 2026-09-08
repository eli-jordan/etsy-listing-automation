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

    shop_id: int | None = None

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


class EtsyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    who_made: str
    when_made: str
    is_supply: bool
    renewal: Literal["manual", "auto"] = "manual"

    # Required only by the Etsy stages (Phase 3). All three are numeric ids
    # that normally come back *from* the Etsy API, so demanding them at load
    # time made a workspace unusable for the earlier phases -- you would need
    # ids you cannot obtain until the phase that fetches them.
    #
    # `shop_id` was the exception until Phase 2, on the reasoning that it
    # identifies which shop the workspace targets and so is a defining
    # property rather than a per-stage detail. That is true of a finished
    # workspace and false of a new one: a Phase 2 workspace creates Printify
    # products and never speaks to Etsy, and `setup` has to be runnable before
    # an Etsy shop exists. Requiring it bought one placeholder `12345678` --
    # a number that looks real enough to reach Etsy in Phase 3.
    shop_id: int | None = None
    shop_section_id: int | None = None
    return_policy_id: int | None = None

    def require_shop_id(self) -> int:
        if self.shop_id is None:
            raise MissingDefaultError(
                "etsy.shop_id",
                "read or patch a listing on Etsy",
                "It is the number in your Etsy shop manager's URL; Phase 3's "
                "`auth` flow can also read it back from the Etsy API.",
            )
        return self.shop_id

    def require_shop_section_id(self) -> int:
        if self.shop_section_id is None:
            raise MissingDefaultError(
                "etsy.shop_section_id",
                "file a listing under a shop section",
                "Create the section in Etsy's shop manager; Phase 3's setup "
                "flow reads the sections back from the Etsy API and can fill "
                "in the id.",
            )
        return self.shop_section_id

    def require_return_policy_id(self) -> int:
        if self.return_policy_id is None:
            raise MissingDefaultError(
                "etsy.return_policy_id",
                "attach a return policy to a listing",
                "Configure the policy in Etsy's shop manager; Phase 3's setup "
                "flow reads the policies back from the Etsy API and can fill "
                "in the id.",
            )
        return self.return_policy_id


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    etsy: EtsyDefaults
    printify: PrintifyDefaults = PrintifyDefaults()
    currency: str
    preferred_print_provider: str | None = None

    @classmethod
    def load(cls, path: Path) -> Defaults:
        if not path.is_file():
            raise ConfigLoadError(path, "file not found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

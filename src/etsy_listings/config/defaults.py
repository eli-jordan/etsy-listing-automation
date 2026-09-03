"""``defaults.yaml``: shop-wide configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.config.errors import ConfigLoadError, format_validation_error


class MissingEtsyDefaultError(ValueError):
    """A ``defaults.yaml`` field that only some phases need, asked for by a
    phase that needs it.

    Raised at the point of use rather than at load, so a workspace can be set
    up and used for everything that doesn't need the field yet.
    """

    def __init__(self, field: str, needed_to: str, how_to_find: str) -> None:
        self.field = field
        super().__init__(
            f"defaults.yaml: etsy.{field} is not set, and is required to {needed_to}. {how_to_find}"
        )


class EtsyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: int
    who_made: str
    when_made: str
    is_supply: bool
    renewal: Literal["manual", "auto"] = "manual"

    # Required only by the Etsy stages (Phase 3). Both are numeric ids that
    # normally come back *from* the Etsy API, so demanding them at load time
    # made a workspace unusable for the earlier phases -- you would need ids
    # you cannot obtain until the phase that fetches them. `shop_id` stays
    # required because it identifies which shop this workspace targets, which
    # is a defining property of the workspace rather than a per-stage detail.
    shop_section_id: int | None = None
    return_policy_id: int | None = None

    def require_shop_section_id(self) -> int:
        if self.shop_section_id is None:
            raise MissingEtsyDefaultError(
                "shop_section_id",
                "file a listing under a shop section",
                "Create the section in Etsy's shop manager; Phase 3's setup "
                "flow reads the sections back from the Etsy API and can fill "
                "in the id.",
            )
        return self.shop_section_id

    def require_return_policy_id(self) -> int:
        if self.return_policy_id is None:
            raise MissingEtsyDefaultError(
                "return_policy_id",
                "attach a return policy to a listing",
                "Configure the policy in Etsy's shop manager; Phase 3's setup "
                "flow reads the policies back from the Etsy API and can fill "
                "in the id.",
            )
        return self.return_policy_id


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    etsy: EtsyDefaults
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

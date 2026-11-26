"""``listing-templates/{name}/template.yaml``: a listing's reusable production
settings."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, model_validator

from etsy_listings.core.config.errors import (
    load_model,
)
from etsy_listings.core.config.listing import MediaEntry, check_production_fields, resolve_price
from etsy_listings.core.config.money import Money
from etsy_listings.core.config.pricing_plan import PricingPlan


class TemplateDescriptionConfig(BaseModel):
    """A description *body*: inline ``text`` or a common-copy ``ref``, and no
    ``lead``. The lead is the opening a shopper reads about one design, so
    every listing made from the template gets its own (spec, copy table)."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    ref: str | None = None

    @model_validator(mode="after")
    def _at_most_one_body_source(self) -> TemplateDescriptionConfig:
        if self.text is not None and self.ref is not None:
            raise ValueError("etsy.description: text and ref must not both be set")
        return self


class TemplateEtsyConfig(BaseModel):
    """`EtsyListingConfig` without the copy an instance writes for itself."""

    model_config = ConfigDict(extra="forbid")

    description: TemplateDescriptionConfig = TemplateDescriptionConfig()
    renewal: Literal["manual", "auto"] | None = None
    section: str | None = None
    shipping_profile: str | None = None
    variation_images: str | None = None


class ListingTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_profile: str
    colors: list[str]
    prices: dict[str, Money] = {}
    pricing_plan: str | None = None
    price_overrides: dict[str, dict[str, Money]] = {}
    etsy: TemplateEtsyConfig = TemplateEtsyConfig()
    media: list[MediaEntry]

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> ListingTemplate:
        check_production_fields(
            colors=self.colors,
            prices=self.prices,
            price_overrides=self.price_overrides,
            media=self.media,
            currency=(info.context or {}).get("currency"),
        )
        return self

    def resolved_price(
        self, color: str, size: str, *, pricing_plan: PricingPlan | None = None
    ) -> Money:
        return resolve_price(
            self.prices, self.price_overrides, color, size, pricing_plan=pricing_plan
        )

    @classmethod
    def load(
        cls, path: Path, *, currency: str, read: Callable[[Path], bytes] = Path.read_bytes
    ) -> ListingTemplate:
        return load_model(
            cls,
            path,
            context={"currency": currency},
            read=read,
            missing="listing template file not found",
        )

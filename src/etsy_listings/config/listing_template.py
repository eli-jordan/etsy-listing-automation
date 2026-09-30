"""``listing-templates/{name}/template.yaml``: a listing's reusable production
settings, and nothing about one design (A35; spec *Listing templates*).

A listing template is its own resource, not a listing kind and not a listing
with placeholder fields. What it has is exactly the spec's copy table --
garment, colours, pricing, gallery, description body, Etsy production
settings -- and what it lacks it cannot carry: ``design``, ``artwork``,
``brief``, ``lifecycle``, ``etsy.title``, ``etsy.tags`` and
``etsy.description.lead`` are refused as extra fields rather than ignored,
so a hand-edited file that names one is told so instead of quietly dropping
it at the next save.

The structural rules it shares with a listing are the listing's own
(:func:`~etsy_listings.config.listing.check_production_fields`): every listing
made from a template must load, so the two cannot be allowed to disagree about
what a well-formed gallery or price is. Completeness -- is there a garment, a
colour, a price source -- is `config/listing_validation.py`'s
``check_listing_template`` (A36), for the same reason a listing's is.

A ``./`` ref here names a file beneath the template's own directory, where
Save as listing template copies a listing's local media
(``Workspace.resolve_template_ref``). A bare ref is a shared workspace ref,
exactly as in a listing (PRD 73).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, model_validator

from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.listing import MediaEntry, check_production_fields, resolve_price
from etsy_listings.config.money import Money, PriceField
from etsy_listings.config.pricing_plan import PricingPlan


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
    """`EtsyListingConfig` without the copy an instance writes for itself.
    The four settings keep the meanings `EtsyListingConfig` documents."""

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
    prices: dict[str, PriceField] = {}
    pricing_plan: str | None = None
    price_overrides: dict[str, dict[str, PriceField]] = {}
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
        """`Listing.resolved_price`'s rule: what a listing made from this
        template would charge, which is what the editor's Pricing tab shows."""
        return resolve_price(
            self.prices, self.price_overrides, color, size, pricing_plan=pricing_plan
        )

    @classmethod
    def load(
        cls, path: Path, *, currency: str, read: Callable[[Path], bytes] = Path.read_bytes
    ) -> ListingTemplate:
        """``read`` is how the file's bytes are fetched: the workspace passes
        its retrying reader (A37), which ``config`` cannot import without a
        cycle through the workspace package."""
        if not path.is_file():
            raise ConfigLoadError(path, "listing template file not found")
        raw = yaml.safe_load(read(path).decode("utf-8")) or {}
        try:
            return cls.model_validate(raw, context={"currency": currency})
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

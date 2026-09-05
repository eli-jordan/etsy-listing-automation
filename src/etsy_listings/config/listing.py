"""``listings/{name}/listing.yaml``: everything commercial and creative, PRD 8a."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Final, Literal

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.money import Money, PriceField, require_currency
from etsy_listings.config.pricing_plan import PricingPlan

GENERATE: Final = "<generate>"

MAX_MEDIA_ENTRIES = 10
MAX_TAGS = 13
MAX_TAG_LENGTH = 20
MAX_TITLE_LENGTH = 140


def _coerce_design(raw: Any) -> dict[str, str]:  # noqa: ANN401 - pydantic validator boundary
    """A bare path is shorthand for the common single-artwork case -- it
    normalises to one entry, so artwork resolution's "sole key" rule (item 2)
    picks it with no other machinery involved."""
    if isinstance(raw, str):
        return {"default": raw}
    result: dict[str, str] = raw
    return result


DesignField = Annotated[dict[str, str], BeforeValidator(_coerce_design)]
"""Artwork key -> workspace-relative design path. A design needing different
ink for light vs dark shirts carries more than one entry, conventionally keyed
``on-light``/``on-dark``; resolution order lives in the render stage
(engine/stages/render.py), since it needs the profile and template too."""


class TemplateMediaEntry(BaseModel):
    """Always-explicit template reference -- there is no bare-colour
    shorthand. ``colour`` is required when the referenced template is
    ``colour-matrix`` kind (which colour's photo) and must be omitted for
    ``multiple``/``single`` kind (exactly one output each, nothing to
    disambiguate)."""

    model_config = ConfigDict(extra="forbid")

    template: str
    colour: str | None = None


MediaEntry = TemplateMediaEntry | str
"""Either an explicit template reference, or a bare path string to a shared
asset under ``common-media/``."""


class EtsyListingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = GENERATE
    description: str = GENERATE
    tags: list[str] | Literal["<generate>"] = GENERATE
    materials: list[str] = []
    renewal: Literal["manual", "auto"] | None = None

    @model_validator(mode="after")
    def _validate_concrete_values(self) -> EtsyListingConfig:
        if self.title != GENERATE and len(self.title) > MAX_TITLE_LENGTH:
            raise ValueError(
                f"etsy.title is {len(self.title)} characters, over Etsy's "
                f"{MAX_TITLE_LENGTH}-character limit"
            )
        if isinstance(self.tags, list):
            if len(self.tags) > MAX_TAGS:
                raise ValueError(
                    f"etsy.tags has {len(self.tags)} tags, over Etsy's {MAX_TAGS}-tag limit"
                )
            for tag in self.tags:
                if len(tag) > MAX_TAG_LENGTH:
                    raise ValueError(
                        f"etsy.tags: {tag!r} is {len(tag)} characters, over Etsy's "
                        f"{MAX_TAG_LENGTH}-character-per-tag limit"
                    )
        return self


class Listing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    design: DesignField
    colors: list[str]
    brief: str
    prices: dict[str, PriceField] = {}
    """Per-size overrides on top of ``pricing_plan`` -- optional and partial.
    A listing with no ``pricing_plan`` must cover every size it needs here,
    exactly as before this field became optional."""
    pricing_plan: str | None = None
    """Workspace-relative path to a ``pricing-plans/*.yaml`` file, resolved
    the same way ``design`` is (not a bare name against a fixed directory,
    unlike ``profile``/``media[].template``) -- see PRD 34. Resolution and
    loading are the caller's job; ``Listing`` never touches ``Workspace``."""
    price_overrides: dict[str, dict[str, PriceField]] = {}
    artwork: dict[str, str] = {}
    """Explicit per-design artwork override, colour -> artwork key. Wins over
    everything else in resolution order (item 2) -- the thing a human is most
    likely to actually revisit per design."""
    etsy: EtsyListingConfig = EtsyListingConfig()
    media: list[MediaEntry]

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> Listing:
        context = info.context or {}
        expected_currency = context.get("currency")
        if expected_currency:
            for size, price in self.prices.items():
                require_currency(price, expected_currency, f"prices.{size}")
            for color, overrides in self.price_overrides.items():
                for size, price in overrides.items():
                    require_currency(price, expected_currency, f"price_overrides.{color}.{size}")

        if self.pricing_plan is None and not self.prices:
            raise ValueError("listing has no pricing_plan and no prices -- set at least one")

        if len(self.media) > MAX_MEDIA_ENTRIES:
            raise ValueError(
                f"media has {len(self.media)} entries, over Etsy's {MAX_MEDIA_ENTRIES}-image limit"
            )

        for color in self.price_overrides:
            if color not in self.colors:
                raise ValueError(
                    f"price_overrides has an entry for {color!r}, which is not in colors"
                )

        for color in self.artwork:
            if color not in self.colors:
                raise ValueError(f"artwork has an entry for {color!r}, which is not in colors")

        for entry in self.media:
            if (
                isinstance(entry, TemplateMediaEntry)
                and entry.colour is not None
                and entry.colour not in self.colors
            ):
                raise ValueError(
                    f"media references colour {entry.colour!r}, which is not in colors"
                )

        return self

    @classmethod
    def load(cls, path: Path, *, currency: str) -> Listing:
        if not path.is_file():
            raise ConfigLoadError(path, "listing file not found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw, context={"currency": currency})
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

    def resolved_price(
        self, color: str, size: str, *, pricing_plan: PricingPlan | None = None
    ) -> Money:
        """``price_overrides`` > ``prices`` > the referenced pricing plan's own
        (override-then-flat) resolution. ``pricing_plan`` is an already-loaded
        object, not the ``str`` ref -- loading it is the caller's job, the same
        point ``design`` refs get resolved (see the ``pricing_plan`` field's
        docstring)."""
        override = self.price_overrides.get(color, {}).get(size)
        if override is not None:
            return override
        direct = self.prices.get(size)
        if direct is not None:
            return direct
        if pricing_plan is not None:
            plan_price = pricing_plan.resolved_price(color, size)
            if plan_price is not None:
                return plan_price
        raise KeyError(
            f"no price for size {size!r} (colour {color!r}): not in price_overrides, "
            f"prices, or the referenced pricing plan"
        )

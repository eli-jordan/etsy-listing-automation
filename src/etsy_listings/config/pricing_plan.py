"""``pricing-plans/{name}.yaml``: a reusable, per-size starting price table.

Referenced by a listing's ``pricing_plan:`` field as a workspace-relative
path, resolved the same way ``design:`` is (PRD 34) -- not a bare name
against a fixed directory the way ``garment_profile:``/``media[].template``
are. No name/label field: the filename is the identity.
``garment_profile`` is a bare-name back-reference to the garment profile
this plan was built for, in the same style as ``Listing.garment_profile`` --
unvalidated against an actual garment profile file at load time, for the
same reason ``Listing.garment_profile`` is (PRD 33).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, model_validator

from etsy_listings.config.errors import ConfigLoadError, format_validation_error
from etsy_listings.config.money import Money, PriceField, require_currency


class PricingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_profile: str
    prices: dict[str, PriceField]
    price_overrides: dict[str, dict[str, PriceField]] = {}
    """Same shape as ``Listing.price_overrides`` -- a whole tier can carry a
    colour markup, not just one listing (PRD 33)."""

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> PricingPlan:
        context = info.context or {}
        expected_currency = context.get("currency")
        if expected_currency:
            for size, price in self.prices.items():
                require_currency(price, expected_currency, f"prices.{size}")
            for color, overrides in self.price_overrides.items():
                for size, price in overrides.items():
                    require_currency(price, expected_currency, f"price_overrides.{color}.{size}")
        return self

    @classmethod
    def load(cls, path: Path, *, currency: str) -> PricingPlan:
        if not path.is_file():
            raise ConfigLoadError(path, "pricing plan file not found")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw, context={"currency": currency})
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

    def resolved_price(self, color: str, size: str) -> Money | None:
        """``None`` (not ``KeyError``) when this plan doesn't cover the size --
        the caller (``Listing.resolved_price``) still has its own
        ``prices``/``price_overrides`` to fall back to before it's a real
        error."""
        override = self.price_overrides.get(color, {}).get(size)
        if override is not None:
            return override
        return self.prices.get(size)

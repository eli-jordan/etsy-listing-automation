from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, model_validator

from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error, parse_yaml
from etsy_listings.core.config.money import Money, require_currency


class PricingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_profile: str
    prices: dict[str, Money]
    price_overrides: dict[str, dict[str, Money]] = {}
    """Same shape as ``Listing.price_overrides`` -- a whole tier can carry a
    colour markup, not just one listing."""

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
        raw = parse_yaml(path, path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw, context={"currency": currency})
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

    def resolved_price(self, color: str, size: str) -> Money | None:
        override = self.price_overrides.get(color, {}).get(size)
        if override is not None:
            return override
        return self.prices.get(size)

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
from etsy_listings.config.money import Money, require_currency

GENERATE: Final = "<generate>"

MAX_MEDIA_ENTRIES = 10
MAX_TAGS = 13
MAX_TAG_LENGTH = 20
MAX_TITLE_LENGTH = 140


def _coerce_money(raw: Any) -> Money:  # noqa: ANN401 - pydantic validator boundary
    return Money.parse(raw)


PriceField = Annotated[Money, BeforeValidator(_coerce_money)]


class MockupMediaEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mockup: str


MediaEntry = MockupMediaEntry | str
"""Either ``{mockup: <colour-slug>}`` (PRD 25, resolved via the render cache) or a
bare path string to a shared asset under ``common-media/``."""


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
    design: str
    colors: list[str]
    brief: str
    prices: dict[str, PriceField]
    price_overrides: dict[str, dict[str, PriceField]] = {}
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

        if len(self.media) > MAX_MEDIA_ENTRIES:
            raise ValueError(
                f"media has {len(self.media)} entries, over Etsy's "
                f"{MAX_MEDIA_ENTRIES}-image limit"
            )

        for color in self.price_overrides:
            if color not in self.colors:
                raise ValueError(
                    f"price_overrides has an entry for {color!r}, which is not in colors"
                )

        for entry in self.media:
            if isinstance(entry, MockupMediaEntry) and entry.mockup not in self.colors:
                raise ValueError(
                    f"media references mockup {entry.mockup!r}, which is not in colors"
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

    def resolved_price(self, color: str, size: str) -> Money:
        override = self.price_overrides.get(color, {}).get(size)
        if override is not None:
            return override
        try:
            return self.prices[size]
        except KeyError as exc:
            raise KeyError(f"no price for size {size!r} (colour {color!r})") from exc

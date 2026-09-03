"""``defaults.yaml``: shop-wide configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from etsy_listings.config.errors import ConfigLoadError, format_validation_error


class EtsyDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: int
    who_made: str
    when_made: str
    is_supply: bool
    shop_section_id: int
    return_policy_id: int
    renewal: Literal["manual", "auto"] = "manual"


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

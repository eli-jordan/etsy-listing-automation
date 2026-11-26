from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from etsy_listings.core.config.errors import ConfigLoadError, format_validation_error, parse_yaml


class PrintArea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int
    height: int


class BlueprintRef(BaseModel):
    """``brand`` and ``model`` identify the blank. Printify's titles are
    generic and rewritten over time, so ``title`` takes no part in matching."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    brand: str
    model: str
    title: str = ""
    """Refreshed by ``new``; a drifted title is stale prose, not a broken profile."""

    def __str__(self) -> str:
        return f"{self.brand} {self.model}".strip()

    @property
    def display_title(self) -> str:
        return self.title or str(self)


class GarmentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint: BlueprintRef
    print_provider: str
    placeholder: str
    print_area: PrintArea
    sizes: list[str]
    materials: list[str] = []
    """The fibre materials Etsy displays, the same for every listing on this garment."""
    colors: dict[str, Literal["light", "dark"]] = {}
    """Classified by hand in ``new``: Printify's catalog gives no hex colour. Picks the light or
    dark ink design for a listing with more than one design file."""

    preview_template: str | None = None
    """A ``colour-matrix`` template the editor uses to judge colours; not a ``media:`` default.
    Hand-edited, like ``colors:``."""

    @field_validator("preview_template", mode="before")
    @classmethod
    def _blank_preview_template_is_unset(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @classmethod
    def load(cls, path: Path) -> GarmentProfile:
        if not path.is_file():
            raise ConfigLoadError(path, "garment profile file not found")
        raw = parse_yaml(path, path.read_text(encoding="utf-8")) or {}
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise format_validation_error(path, exc) from exc

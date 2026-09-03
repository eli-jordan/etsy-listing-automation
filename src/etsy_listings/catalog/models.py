"""Printify catalog reference data: blueprints, print providers, variants.

This is the read-only, unauthenticated half of the Printify API (PRD 7b) --
distinct from the shop-scoped product CRUD client that ``clients/printify/``
adds in a later phase.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Blueprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    brand: str
    model: str


class PrintProvider(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str


class VariantOptions(BaseModel):
    model_config = ConfigDict(frozen=True)

    color: str
    size: str


class Variant(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    options: VariantOptions


class PrintAreaPlaceholder(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: str
    width: int
    height: int


class VariantSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    variants: tuple[Variant, ...]
    placeholders: tuple[PrintAreaPlaceholder, ...]

    @property
    def colors(self) -> list[str]:
        seen: dict[str, None] = {}
        for variant in self.variants:
            seen.setdefault(variant.options.color, None)
        return list(seen)

    def placeholder(self, position: str) -> PrintAreaPlaceholder | None:
        return next((p for p in self.placeholders if p.position == position), None)

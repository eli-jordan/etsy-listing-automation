"""Printify catalog reference data: blueprints, print providers, variants.

This is the read-only half of the Printify API (PRD 7b) -- distinct from the
shop-scoped product CRUD client that ``clients/printify/`` adds in a later
phase. Read-only, but not unauthenticated: every catalog call needs a token
with the ``catalog.read`` scope, same as the rest of the API.
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


class PrintAreaPlaceholder(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: str
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


class Variant(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    options: VariantOptions
    placeholders: tuple[PrintAreaPlaceholder, ...] = ()
    """**Per variant, which is where Printify actually puts them.** The
    variants endpoint has no top-level ``placeholders`` key; each variant
    carries its own list. Reading the response as though it did is how every
    profile came out with no ``front`` placeholder and ``new`` died on
    "Available: (none)".

    They are per-variant because they genuinely differ: on Comfort Colors
    1717 / Monster Digital, ``front`` is 3461x3955 on the small sizes and
    4200x4800 on the large ones."""


class VariantSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    variants: tuple[Variant, ...]

    @property
    def colors(self) -> list[str]:
        seen: dict[str, None] = {}
        for variant in self.variants:
            seen.setdefault(variant.options.color, None)
        return list(seen)

    def positions(self) -> list[str]:
        """Every print position this combination offers, first seen first."""
        seen: dict[str, None] = {}
        for variant in self.variants:
            for placeholder in variant.placeholders:
                seen.setdefault(placeholder.position, None)
        return list(seen)

    def placeholder_sizes(self, position: str) -> list[PrintAreaPlaceholder]:
        """Every distinct size offered at ``position``, largest first.

        Distinct by dimensions rather than by variant: a 229-variant set
        typically offers two or three sizes across all of them, and the same
        size repeated under several decoration methods.
        """
        distinct = {
            (p.width, p.height): p
            for variant in self.variants
            for p in variant.placeholders
            if p.position == position
        }
        return sorted(distinct.values(), key=lambda p: (p.area, p.width, p.height), reverse=True)

    def placeholder(self, position: str) -> PrintAreaPlaceholder | None:
        """The **largest** size offered at ``position``, or ``None``.

        A profile carries one print area (PRD 8a) and the catalog offers
        several, so one has to win. The largest does, because the print area
        is a resolution target -- a design must come within 10% of it in each
        axis (PRD 38) -- and art sized for the 3XL panel still covers the S
        panel, while the reverse prints soft on the sizes that need it most.
        """
        sizes = self.placeholder_sizes(position)
        return sizes[0] if sizes else None


class ShippingCost(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str
    cost: int
    """Cents, as Printify sends it -- not a ``Money`` (that type wants a
    workspace-currency-checked amount; this is a raw USD catalog figure a
    caller converts, it doesn't validate against ``shop.yaml`` itself)."""


class ShippingProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    variant_ids: tuple[int, ...]
    first_item: ShippingCost
    additional_items: ShippingCost


class ShippingRates(BaseModel):
    model_config = ConfigDict(frozen=True)

    profiles: tuple[ShippingProfile, ...]

    def first_item_cost_cents(self, variant_id: int) -> int | None:
        for profile in self.profiles:
            if variant_id in profile.variant_ids:
                return profile.first_item.cost
        return None

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.config.money import Money
from etsy_listings.core.engine.stage import Blocked

__all__ = [
    "AppliedPrintArea",
    "AppliedProduct",
    "AppliedVariant",
    "ArtworkGroup",
    "PricedVariant",
    "PrintifyProductDesired",
    "check_garment_unchanged",
    "money",
]


class AppliedVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    price: int
    colour_slug: str
    """Carried, not looked up, so a colour Printify has since discontinued
    still has a name to be reported removed by."""


@dataclass(frozen=True)
class ArtworkGroup:
    design: Path
    design_hash: str
    colours: tuple[str, ...]


class AppliedPrintArea(BaseModel):
    """ADR-0053."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    design_hash: str
    variant_ids: list[int]


class AppliedProduct(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str
    description: str
    blueprint_id: int
    print_provider_id: int
    position: str
    variants: list[AppliedVariant]
    print_areas: list[AppliedPrintArea]

    @property
    def prices(self) -> dict[int, int]:
        return {variant.id: variant.price for variant in self.variants}


@dataclass(frozen=True)
class PricedVariant:
    id: int
    colour_slug: str
    size: str
    price: int
    """Minor units of the sales channel's currency."""


@dataclass(frozen=True)
class PrintifyProductDesired:
    title: str
    description: str
    blueprint_id: int
    print_provider_id: int
    position: str
    variants: tuple[PricedVariant, ...]
    groups: tuple[ArtworkGroup, ...]
    missing: tuple[tuple[str, str], ...] = ()
    """``(colour_slug, size)`` cells the catalog no longer offers; never fatal."""
    currency: str = ""

    @property
    def prices(self) -> dict[int, int]:
        return {variant.id: variant.price for variant in self.variants}

    def variant_ids(self, group: ArtworkGroup) -> tuple[int, ...]:
        colours = set(group.colours)
        return tuple(sorted(v.id for v in self.variants if v.colour_slug in colours))

    def applied(self) -> AppliedProduct:
        """Variants are a list sorted by id: a JSON round-trip turns integer
        keys into strings, which would differ on every run."""
        return AppliedProduct(
            title=self.title,
            description=self.description,
            blueprint_id=self.blueprint_id,
            print_provider_id=self.print_provider_id,
            position=self.position,
            variants=[
                AppliedVariant(id=variant.id, price=variant.price, colour_slug=variant.colour_slug)
                for variant in sorted(self.variants, key=lambda v: v.id)
            ],
            print_areas=sorted(
                (
                    AppliedPrintArea(
                        design_hash=group.design_hash,
                        variant_ids=list(self.variant_ids(group)),
                    )
                    for group in self.groups
                ),
                key=lambda area: area.design_hash,
            ),
        )


def check_garment_unchanged(
    was: AppliedProduct | None, *, blueprint_id: int, print_provider_id: int
) -> Blocked | None:
    if was is None:
        return None

    changes: list[str] = []
    if was.blueprint_id != blueprint_id:
        changes.append(f"blueprint {was.blueprint_id} -> {blueprint_id}")
    if was.print_provider_id != print_provider_id:
        changes.append(f"print provider {was.print_provider_id} -> {print_provider_id}")
    if not changes:
        return None

    return Blocked(
        f"this listing's Printify product was created with a different garment: "
        f"{', '.join(changes)}.\n"
        f"Printify cannot change either on an existing product -- it accepts the "
        f"request, answers 200, and changes nothing.\n"
        f"Start a new listing for the new garment, or make the change by hand in "
        f"Printify and Etsy. Recreating the product here would discard the Etsy "
        f"listing's reviews and favourites."
    )


def money(minor_units: int, currency: str) -> Money:
    return Money(Decimal(minor_units) / 100, currency)

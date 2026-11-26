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
    """Which colour this variant id sold as, at the time it was applied
    . Carried on the variant itself, rather than looked up from this
    run's catalog resolution, because a colour Printify has since discontinued
     would otherwise have no name to be reported *removed* by --
    exactly the run a removal needs to be visible on."""


@dataclass(frozen=True)
class ArtworkGroup:
    design: Path
    design_hash: str
    colours: tuple[str, ...]


class AppliedPrintArea(BaseModel):
    """One print area as last applied: the file's content hash and the
    variants that print it (ADR-0053).

    A lockfile written before ADR-0053 also carries the ``artwork`` key each area
    was grouped by. ``extra="ignore"`` reads it past, and since that
    document's hash and variant ids are the ones this version computes for an
    unchanged listing, an upgrade sends Printify nothing.
    """

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
    """One colour x size cell, and what it sells for.

    A :class:`~etsy_listings.core.clients.printify.resolve.ResolvedVariant` plus a
    price, which is the whole of what this stage needs about a variant. It
    replaces three parallel structures that between them described exactly
    this: ``prices`` keyed by id, ``price_labels`` keyed by id, and the full
    ``VariantResolution``. ``price_labels`` existed only because ``prices``
    had thrown away the colour and size the resolution was still carrying.
    """

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
    """``(colour_slug, size)`` cells the catalog no longer offers. Reported,
    never fatal -- missing variant cells."""
    currency: str = ""

    @property
    def prices(self) -> dict[int, int]:
        return {variant.id: variant.price for variant in self.variants}

    def variant_ids(self, group: ArtworkGroup) -> tuple[int, ...]:
        colours = set(group.colours)
        return tuple(sorted(v.id for v in self.variants if v.colour_slug in colours))

    def applied(self) -> AppliedProduct:
        """Variants are a list sorted by id rather than a mapping, because a JSON
        round-trip turns integer keys into strings and the comparison would
        then find a difference on every run."""
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

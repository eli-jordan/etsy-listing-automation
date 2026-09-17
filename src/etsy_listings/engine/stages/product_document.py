"""The product stage's two documents, and the gate that reads one of them.

Three things that are one subject: the **desired** product a listing asks for
(:class:`PrintifyProductDesired`), the **applied** document recording what was
last sent (:class:`AppliedProduct`, A2), and
:func:`check_garment_unchanged`, which is a question about the applied
document and nothing else.

They live here rather than beside the stage because two modules need them and
neither should import the other: the stage builds them and sends them, and
:mod:`~etsy_listings.engine.stages.product_diff` compares them. A module both
can depend on is what keeps the comparison reachable without a workspace, a
lockfile and two fake clients.

Nothing here does I/O, holds a client, or reads a clock -- which is what makes
the comparison built on it a pure function, and what lets
``tests/unit/test_product_document.py`` exercise it directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from etsy_listings.config.money import Money
from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.placement import ArtworkGroup

__all__ = [
    "AppliedPrintArea",
    "AppliedProduct",
    "AppliedVariant",
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
    (A30). Carried on the variant itself, rather than looked up from this
    run's catalog resolution, because a colour Printify has since discontinued
    (PRD 46) would otherwise have no name to be reported *removed* by --
    exactly the run a removal needs to be visible on."""


class AppliedPrintArea(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    artwork: str
    design_hash: str
    variant_ids: list[int]


class AppliedProduct(BaseModel):
    """The verbatim last-applied document (A2), as a type rather than a dict.

    It is *stored* as JSON, and it used to be *read back* as JSON too:
    ``applied.get("title")`` beside ``document["print_areas"]`` beside
    ``entry["id"]``, spelled again in each of the three functions that
    compared them. Nothing stopped one drifting from the others, and the shape
    of a missing value was whatever ``.get`` happened to return -- which is why
    the price diff carried a ``("?", "?")`` fallback for a lookup that cannot
    miss.

    Typed, the comparison is field access and the fallbacks are gone. The bytes
    on disk are unchanged: :meth:`PrintifyProductDesired.applied` dumps exactly
    the document that was written before, so no existing lockfile is
    invalidated and no product is re-applied for having been re-read.

    It has no ``parse()`` of its own. Decoding a stage's subtree -- including
    what a document that will not decode means -- is
    :meth:`~etsy_listings.engine.lock.Lockfile.parse_applied_for`'s, so that
    the rule has one implementation rather than one per stage.
    """

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

    A :class:`~etsy_listings.clients.printify.resolve.ResolvedVariant` plus a
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
    """Minor units of the sales channel's currency (PRD 39/40)."""


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
    never fatal -- PRD 46."""
    currency: str = ""

    @property
    def prices(self) -> dict[int, int]:
        """``{variant_id: price}`` -- the shape the wire wants, and the only
        place that shape is needed."""
        return {variant.id: variant.price for variant in self.variants}

    def variant_ids(self, group: ArtworkGroup) -> tuple[int, ...]:
        """The Printify variants a group's colours resolve to, in id order.

        The group itself knows only colours -- which ink a colour gets is a
        fact about the listing, not about Printify -- so turning them into ids
        is this stage's half of the job, and it is the one place that does it.

        **Sorted**, and that is a fix rather than a tidying. These ids go into
        ``print_areas[].variant_ids``, which is part of the hashed document,
        and they used to come out in resolution order -- colour-outer,
        size-inner, so the order the listing happens to write ``colors:`` in.
        Reordering that list changed ``input_hash`` and re-applied a product
        nothing about which had changed. Printify does not care about the
        order, so nothing is lost by making the document not care either.
        """
        colours = set(group.colours)
        return tuple(sorted(v.id for v in self.variants if v.colour_slug in colours))

    def applied(self) -> AppliedProduct:
        """The hashable last-applied form: no paths, no upload ids, no clock.

        Variants are a list sorted by id rather than a mapping, because a JSON
        round-trip turns integer keys into strings and the comparison would
        then find a difference on every run. The sort is also what keeps the
        hash independent of the colour-outer, size-inner order the catalog
        resolves cells in.

        **Print areas are sorted by artwork** for the same reason, one level
        up. ``group_by_artwork`` deduplicates in first-seen order on purpose,
        so the payload's print areas follow the order the listing wrote its
        colours in -- which is right for the wire and wrong for a document
        that is compared and hashed: moving a colour to the top of ``colors:``
        reordered this list and made an unchanged product look changed. The
        wire keeps its order; only the record is canonicalised. ``artwork`` is
        the key ``group_by_artwork`` partitioned on, so it is unique here.
        """
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
                        artwork=group.artwork,
                        design_hash=group.design_hash,
                        variant_ids=list(self.variant_ids(group)),
                    )
                    for group in self.groups
                ),
                key=lambda area: area.artwork,
            ),
        )


def check_garment_unchanged(
    was: AppliedProduct | None, *, blueprint_id: int, print_provider_id: int
) -> Blocked | None:
    """Refuse a garment or printer change on a listing that already has a product.

    A deliberate refusal, not a missing feature (PRD 37). Printify ignores both
    fields on an update -- ``200``, no change -- so the only automated route is
    delete-and-recreate, which takes the Etsy listing behind the product with
    it: reviews, favourites, search history, to save retyping a short YAML
    file. A listing is cheap; the listing's history is not.

    Here rather than in ``gates``, which is for checks no single stage owns:
    this one is entirely about this stage's own applied document, and it needed
    that document's type to stop reading it as a dict.
    """
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
    """Minor units back into the form the config was written in."""
    return Money(Decimal(minor_units) / 100, currency)

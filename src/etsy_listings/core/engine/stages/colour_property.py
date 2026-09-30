"""Which of Etsy's inventory properties is the colour, and what its values are.

Matched by **value overlap, never by name or id** (decision 6): the property's
name is the blueprint's own option name -- "Comfort Colors® Colors" on one
garment, "Colors" on the next -- so a rule that read it would break on the
first garment change, silently, by finding nothing.

Extracted from the `etsy_media` stage for the reason
:mod:`~etsy_listings.engine.stages.product_diff` was extracted from the
product stage: it was already pure -- a function of an inventory, the
listing's colours and the slug exceptions, with no workspace, no client and no
lockfile -- but it was not *reachable*. Its only exercise was a full
plan-and-execute against a seeded fake, which is why the branch that matters
most, the two-way tie, went unasserted: a tie is the case where guessing
wrong links every swatch to the wrong photo, and it is three lines that have
to stay right.
"""

from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.clients.etsy.models import Inventory
from etsy_listings.config.slug import ColourExceptions, slugify


@dataclass(frozen=True)
class ColourProperty:
    """The property a variation image is hung on, and every colour slug it
    offers, keyed the way this tool names colours rather than the way Etsy
    does."""

    property_id: int
    value_id_by_slug: dict[str, int]


def resolve_colour_property(
    inventory: Inventory, colours: tuple[str, ...], exceptions: ColourExceptions
) -> ColourProperty | None:
    """The inventory property whose values slugify onto ``colours``.

    ``None`` when nothing overlaps, and ``None`` when two properties overlap
    equally -- both are reported by the caller and neither is guessed at. A
    wrong guess here is not a visible failure: it links every swatch to a
    photo of a different colour, and the API says nothing about it.
    """
    candidates = _slugged_values(inventory, exceptions)

    wanted = set(colours)
    overlaps = {pid: set(mapping) & wanted for pid, mapping in candidates.items()}
    scored = [(pid, len(overlap)) for pid, overlap in overlaps.items() if overlap]
    if not scored:
        return None
    best_score = max(score for _, score in scored)
    winners = [pid for pid, score in scored if score == best_score]
    if len(winners) != 1:
        return None
    return ColourProperty(property_id=winners[0], value_id_by_slug=candidates[winners[0]])


def _slugged_values(
    inventory: Inventory, exceptions: ColourExceptions
) -> dict[int, dict[str, int]]:
    """Every property's values, slug -> value id.

    ``zip(strict=False)`` deliberately: ``values`` and ``value_ids`` are two
    parallel lists in Etsy's own response, and a property where they disagree
    in length is one this tool should ignore rather than fail the whole media
    sync over.
    """
    candidates: dict[int, dict[str, int]] = {}
    for product in inventory.products:
        for property_value in product.property_values:
            mapping = candidates.setdefault(property_value.property_id, {})
            for value, value_id in zip(
                property_value.values, property_value.value_ids, strict=False
            ):
                mapping[exceptions.get(value) or slugify(value)] = value_id
    return candidates

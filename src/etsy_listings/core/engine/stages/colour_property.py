from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.core.clients.etsy.models import Inventory
from etsy_listings.core.config.slug import ColourExceptions, slugify


@dataclass(frozen=True)
class ColourProperty:
    property_id: int
    value_id_by_slug: dict[str, int]


def resolve_colour_property(
    inventory: Inventory, colours: tuple[str, ...], exceptions: ColourExceptions
) -> ColourProperty | None:
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
    candidates: dict[int, dict[str, int]] = {}
    for product in inventory.products:
        for property_value in product.property_values:
            mapping = candidates.setdefault(property_value.property_id, {})
            for value, value_id in zip(
                property_value.values, property_value.value_ids, strict=False
            ):
                mapping[exceptions.get(value) or slugify(value)] = value_id
    return candidates

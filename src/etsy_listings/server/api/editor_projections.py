"""Wire fields shared by listing and listing-template editors."""

from collections.abc import Sequence
from typing import Any

from etsy_listings.core.application.listing_reads import PricedSize
from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.server.api.schemas import ResolvedPrice


def wire_prices(prices: Sequence[PricedSize]) -> list[ResolvedPrice]:
    return [ResolvedPrice(size=price.size, amount=str(price.amount)) for price in prices]


def garment_fields(profile: GarmentProfile | None) -> dict[str, Any]:
    return {
        "garment_materials": profile.materials if profile is not None else [],
        "garment_product_type": profile.blueprint.display_title if profile is not None else None,
        "garment_brand": profile.blueprint.brand if profile is not None else None,
        "garment_model": profile.blueprint.model if profile is not None else None,
    }

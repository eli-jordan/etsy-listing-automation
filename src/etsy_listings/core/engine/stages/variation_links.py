"""The per-colour swatch links, set by both `etsy_media` and `etsy_videos`, so
the rule lives in neither stage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from etsy_listings.core.clients.etsy.models import VariationImageLink
from etsy_listings.core.config.listing import TemplateMediaEntry
from etsy_listings.core.config.media import MediaEntry
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.stages.colour_property import resolve_colour_property
from etsy_listings.core.engine.stages.etsy_target import EtsyListingTarget


def manifest_ref(entry: MediaEntry) -> str:
    """The key of ``lock.remote``'s image and video id maps. It holds no
    render output path, so it survives a re-render."""
    if isinstance(entry, str):
        return entry
    return f"{entry.template}:{entry.colour}" if entry.colour is not None else entry.template


def swatch_refs(media: Sequence[MediaEntry], template: str | None) -> dict[str, str]:
    if template is None:
        return {}
    return {
        entry.colour: manifest_ref(entry)
        for entry in media
        if isinstance(entry, TemplateMediaEntry)
        and entry.template == template
        and entry.colour is not None
    }


def set_variation_images(
    ctx: RunContext,
    target: EtsyListingTarget,
    *,
    colours: tuple[str, ...],
    image_id_by_colour: Mapping[str, int],
) -> None:
    client, shop_id, listing_id = target.client, target.shop_id, target.listing_id
    inventory = client.get_listing_inventory(listing_id)
    colour_property = resolve_colour_property(inventory, colours, ctx.workspace.load_exceptions())
    if colour_property is None:
        ctx.emit("variation_images: no single matching colour property on Etsy -- skipped")
        return

    links = [
        VariationImageLink(
            property_id=colour_property.property_id,
            value_id=colour_property.value_id_by_slug[colour],
            image_id=image_id,
        )
        for colour, image_id in image_id_by_colour.items()
        if colour in colour_property.value_id_by_slug
    ]
    ctx.emit(f"setting {len(links)} variation image link(s)")
    client.update_variation_images(shop_id, listing_id, links)

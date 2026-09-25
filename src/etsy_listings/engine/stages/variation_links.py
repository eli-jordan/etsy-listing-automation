"""The per-colour swatch links (PRD 56, decision 6), set by two stages.

`etsy_media` sets them after it uploads and orders the images. `etsy_videos`
sets them again after placing a second video, because placing one means
cutting `image_ids` short for a moment, and detaching an image deletes its
swatch link for good -- restoring the image restores nothing else (decision
9's "What it costs", measured). One rule and two callers, so the rule lives
in neither: a copy in the video stage would be a second answer to "which
image is this colour's swatch", and the first to go stale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from etsy_listings.clients.etsy.listings import EtsyListingClient
from etsy_listings.clients.etsy.models import VariationImageLink
from etsy_listings.config.listing import TemplateMediaEntry
from etsy_listings.config.media import MediaEntry
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.stages.colour_property import resolve_colour_property


def image_ref(template: str, colour: str | None) -> str:
    """A rendered image's manifest ref: ``"{template}:{colour}"``, or the bare
    template name for a `single`/`multiple` one. Stable across a re-render,
    since the render's own output path does not appear in it."""
    return f"{template}:{colour}" if colour is not None else template


def swatch_refs(media: Sequence[MediaEntry], template: str | None) -> dict[str, str]:
    """colour slug -> manifest ref, for every `media:` entry drawn from the
    `variation_images:` template (PRD 56). Empty when the feature is off."""
    if template is None:
        return {}
    return {
        entry.colour: image_ref(entry.template, entry.colour)
        for entry in media
        if isinstance(entry, TemplateMediaEntry)
        and entry.template == template
        and entry.colour is not None
    }


def set_variation_images(
    ctx: RunContext,
    client: EtsyListingClient,
    *,
    shop_id: int,
    listing_id: int,
    colours: tuple[str, ...],
    image_id_by_colour: Mapping[str, int],
) -> None:
    """Bind each colour's swatch to its image, through Etsy's own colour
    property. Skipped, loudly, when the inventory has no single property
    matching the listing's colours -- decision 6's "reports and does
    nothing", not a failure."""
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

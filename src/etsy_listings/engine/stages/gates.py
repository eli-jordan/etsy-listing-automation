"""The checks `plan` runs before any remote write, and refuses on.

All three exist for the same reason: **nothing downstream catches the
mistake.** Printify accepted a 120x140 PNG onto a 4200x4800 print area without
a warning; it answers ``200`` to a blueprint change and silently ignores it;
and it requires a title, so an unresolved ``<generate>`` would be sent as the
literal string and published as one.

They live here rather than inside ``printify_product`` because `plan` has to
be able to run them before it builds a desired document -- a refusal is more
useful than a well-formed payload nobody wants sent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from etsy_listings.config.listing import GENERATE
from etsy_listings.config.profile import Profile
from etsy_listings.errors import UserFacingError

RESOLUTION_TOLERANCE = 0.9
"""A design must reach 90% of the print area on each axis (PRD 38).

Not slack for its own sake. The failure worth catching is the file that is a
tenth of the size; a few percent short upscales invisibly, and a gate at
exactly 100% rejects a 4000x4800 file for a 4200x4800 area -- a rule that
fires on work nobody would call wrong is a rule that gets switched off.
"""


class DesignResolutionError(UserFacingError, ValueError):
    """The design cannot make a good print, and nothing later will say so."""


class GarmentChangedError(UserFacingError, ValueError):
    """The profile now names a different blank than the product was made with."""


class UnresolvedCopyError(UserFacingError, ValueError):
    """Copy that is still a sentinel, or empty."""


def _required_pixels(profile: Profile) -> tuple[int, int]:
    return (
        int(profile.print_area.width * RESOLUTION_TOLERANCE),
        int(profile.print_area.height * RESOLUTION_TOLERANCE),
    )


def check_design_resolution(design: Path, profile: Profile) -> None:
    """Refuse a design that will print soft, or print its background.

    Never auto-upscaled and never converted (PRD 17): a silently upscaled
    design produces a blurry shirt discovered by customer complaint, which is
    the one failure mode this whole gate exists to make impossible.
    """
    if not design.is_file():
        raise DesignResolutionError(f"design file not found: {design}")

    try:
        with Image.open(design) as image:
            width, height = image.size
            mode = image.mode
    except (UnidentifiedImageError, OSError) as exc:
        raise DesignResolutionError(f"{design} is not readable as an image: {exc}") from exc

    if "A" not in mode:
        raise DesignResolutionError(
            f"{design.name} has no alpha channel (mode {mode!r}). A print file without "
            f"transparency prints its background as a rectangle of ink on the shirt. "
            f"Export it as RGBA."
        )

    need_width, need_height = _required_pixels(profile)
    if width < need_width or height < need_height:
        raise DesignResolutionError(
            f"{design.name} is {width}x{height}, too small for this garment's "
            f"{profile.print_area.width}x{profile.print_area.height} print area.\n"
            f"  It needs at least {need_width}x{need_height} "
            f"({RESOLUTION_TOLERANCE:.0%} of the print area on each axis).\n"
            f"  Re-export the design at that size or larger -- it is never upscaled "
            f"for you, because a blurry print is only ever discovered by a customer."
        )


def check_garment_unchanged(
    applied: dict[str, Any] | None, *, blueprint_id: int, print_provider_id: int
) -> None:
    """Refuse a garment or printer change on a listing that already has a product.

    A deliberate refusal, not a missing feature (PRD 37). Printify ignores both
    fields on an update -- ``200``, no change -- so the only automated route is
    delete-and-recreate, which takes the Etsy listing behind the product with
    it: reviews, favourites, search history, to save retyping a short YAML
    file. A listing is cheap; the listing's history is not.
    """
    if not applied:
        return

    changes: list[str] = []
    was_blueprint = applied.get("blueprint_id")
    was_provider = applied.get("print_provider_id")
    if was_blueprint is not None and was_blueprint != blueprint_id:
        changes.append(f"blueprint {was_blueprint} -> {blueprint_id}")
    if was_provider is not None and was_provider != print_provider_id:
        changes.append(f"print provider {was_provider} -> {print_provider_id}")
    if not changes:
        return

    raise GarmentChangedError(
        f"this listing's Printify product was created with a different garment: "
        f"{', '.join(changes)}.\n"
        f"  Printify cannot change either on an existing product -- it accepts the "
        f"request, answers 200, and changes nothing.\n"
        f"  Start a new listing for the new garment, or make the change by hand in "
        f"Printify and Etsy. Recreating the product here would discard the Etsy "
        f"listing's reviews and favourites."
    )


def check_copy_is_concrete(*, title: str, description: str) -> None:
    """Refuse a `<generate>` sentinel or blank copy before a product is created.

    The product carries the listing's own title and description (PRD 44) --
    Printify's create call requires both, and they are the duplicate guard's
    match key (PRD 48). Neither job survives the literal string
    ``"<generate>"``.
    """
    for field, value in (("title", title), ("description", description)):
        if value == GENERATE:
            raise UnresolvedCopyError(
                f"etsy.{field} is still <generate>, and Printify needs a real one to "
                f"create the product with (it is also how a re-run recognises the "
                f"product as this listing's).\n"
                f"  Write it in listing.yaml. Copy generation arrives in Phase 4."
            )
        if not value.strip():
            raise UnresolvedCopyError(
                f"etsy.{field} is empty, and Printify requires it to create a product."
            )

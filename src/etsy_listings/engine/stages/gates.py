"""The checks `plan` runs before any remote write, and refuses on.

Both exist for the same reason: **nothing downstream catches the mistake.**
Printify accepted a 120x140 PNG onto a 4200x4800 print area without a warning,
and it requires a title, so an unresolved ``<generate>`` would be sent as the
literal string and published as one.

They live here rather than inside a stage because they are checks about a
*listing* -- its copy, its artwork -- that any stage shipping either will want,
and because `plan` has to be able to run them before it builds a desired
document: a refusal is more useful than a well-formed payload nobody wants
sent.

``check_garment_unchanged`` used to be here and is not, for the same rule read
the other way: it is entirely about the product stage's own applied document,
which is now a type rather than a dict, and a shared module has no business
knowing that type. It lives beside the document it reads.

**Each returns a** :class:`~etsy_listings.engine.stage.Blocked` **rather than
raising one.** A refusal is something `plan` has to report, and raising made
it something `plan` could only die of: the exception unwound the stage walk,
so a design a hundred pixels short took the render stage's plan with it and
the user saw a single line where a whole listing's intent belonged. Returned,
a refusal is a blocked stage like any other -- the same vocabulary an
unconfigured shop already used. ``apply`` still refuses to run a blocked
stage, which is the half that has to stay hard.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from etsy_listings.config.listing import GENERATE
from etsy_listings.config.profile import Profile
from etsy_listings.engine.stage import Blocked

RESOLUTION_TOLERANCE = 0.9
"""A design must reach 90% of the print area on each axis (PRD 38).

Not slack for its own sake. The failure worth catching is the file that is a
tenth of the size; a few percent short upscales invisibly, and a gate at
exactly 100% rejects a 4000x4800 file for a 4200x4800 area -- a rule that
fires on work nobody would call wrong is a rule that gets switched off.
"""


def _required_pixels(profile: Profile) -> tuple[int, int]:
    return (
        int(profile.print_area.width * RESOLUTION_TOLERANCE),
        int(profile.print_area.height * RESOLUTION_TOLERANCE),
    )


def check_design_resolution(design: Path, profile: Profile) -> Blocked | None:
    """Refuse a design that will print soft, or print its background.

    Never auto-upscaled and never converted (PRD 17): a silently upscaled
    design produces a blurry shirt discovered by customer complaint, which is
    the one failure mode this whole gate exists to make impossible.
    """
    if not design.is_file():
        return Blocked(f"design file not found: {design}")

    try:
        with Image.open(design) as image:
            width, height = image.size
            mode = image.mode
    except (UnidentifiedImageError, OSError) as exc:
        return Blocked(f"{design} is not readable as an image: {exc}")

    if "A" not in mode:
        return Blocked(
            f"{design.name} has no alpha channel (mode {mode!r}). A print file without "
            f"transparency prints its background as a rectangle of ink on the shirt.\n"
            f"Export it as RGBA."
        )

    need_width, need_height = _required_pixels(profile)
    if width < need_width or height < need_height:
        return Blocked(
            f"{design.name} is {width}x{height}, too small for this garment's "
            f"{profile.print_area.width}x{profile.print_area.height} print area.\n"
            f"It needs at least {need_width}x{need_height} "
            f"({RESOLUTION_TOLERANCE:.0%} of the print area on each axis).\n"
            f"Re-export the design at that size or larger -- it is never upscaled "
            f"for you, because a blurry print is only ever discovered by a customer."
        )
    return None


def check_copy_is_concrete(*, title: str, description: str) -> Blocked | None:
    """Refuse a `<generate>` sentinel or blank copy before a product is created.

    The product carries the listing's own title and description (PRD 44) --
    Printify's create call requires both, and they are the duplicate guard's
    match key (PRD 48). Neither job survives the literal string
    ``"<generate>"``.
    """
    for field, value in (("title", title), ("description", description)):
        if value == GENERATE:
            return Blocked(
                f"etsy.{field} is still <generate>, and Printify needs a real one to "
                f"create the product with (it is also how a re-run recognises the "
                f"product as this listing's).\n"
                f"Write it in listing.yaml. Copy generation arrives in Phase 4."
            )
        if not value.strip():
            return Blocked(f"etsy.{field} is empty, and Printify requires it to create a product.")
    return None

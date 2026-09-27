"""What the batch-creation tests need before they can stage anything: a saved
listing template, a print area small enough that a valid design is a few
kilobytes, and design PNGs that differ by content (batch plan PR 2)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from etsy_listings.batches import Upload
from etsy_listings.listing_templates import from_listing, save
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, edit_garment_profile, edit_listing

LISTING_TEMPLATE = "heavyweight-tee"
GARMENT_PROFILE = "comfort-colors-1717"
LOCAL_PICTURE = "./shots/size-chart.png"
"""A listing-local gallery file, so a frozen listing template has an owned
asset to carry into every listing (spec, *Creation and cloning*)."""
DESIGN_SIZE = (90, 108)
"""90% of :func:`small_print_area`'s 100x120 on each axis -- the smallest
design that passes (PRD 38)."""


def small_print_area(root: Path) -> None:
    edit_garment_profile(root, GARMENT_PROFILE, print_area={"width": 100, "height": 120})


def png(seed: int, *, size: tuple[int, int] = DESIGN_SIZE, mode: str = "RGBA") -> bytes:
    """A PNG whose bytes differ from every other ``seed``'s."""
    colour = (seed % 256, seed // 256 % 256, 90, 255)[: len(mode)]
    buffer = BytesIO()
    Image.new(mode, size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def uploads(*files: tuple[str, bytes]) -> list[Upload]:
    return [Upload(filename=name, stream=BytesIO(data)) for name, data in files]


def a_listing_template(workspace: Workspace, name: str = LISTING_TEMPLATE) -> str:
    """The fixture listing saved as a listing template, with one local picture
    appended to its gallery. The print area is shrunk first."""
    small_print_area(workspace.root)
    picture = workspace.listing_dir(FIXTURE_LISTING) / LOCAL_PICTURE.removeprefix("./")
    picture.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (200, 180, 150)).save(picture)
    listing = workspace.load_listing(FIXTURE_LISTING)
    edit_listing(workspace.root, media=[*listing.model_dump(mode="json")["media"], LOCAL_PICTURE])
    save(
        workspace,
        name,
        from_listing(workspace, FIXTURE_LISTING),
        facts=WorkspaceFacts.gather(workspace),
    )
    return name

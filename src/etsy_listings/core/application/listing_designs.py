"""Adding artwork to ``designs/`` from the editor's design strip.

A file dropped on the strip becomes a listing design: a PNG in ``designs/``
that any listing can then point at. That directory holds artwork listings
actually ship and that other listings may already print, so an upload never
overwrites a different file -- a name that is taken by other bytes gets the
next free ``-2``, ``-3`` suffix instead, and the same bytes under the same name
are simply the file that is already there.

Decoding the multipart request is the route's; uploaded bytes and the
filename enter here (module-structure plan, PR 7).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from etsy_listings.core.application.refusals import ListingDesignUploadRefused
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.workspace import Workspace


def save_listing_design(workspace: Workspace, filename: str, payload: bytes) -> str:
    """Add an upload to ``designs/`` and answer the design name it landed
    under. Refuses with :class:`ListingDesignUploadRefused`, writing nothing,
    unless ``filename`` is a plain filename and ``payload`` decodes as a PNG
    -- ``designs/`` holds PNGs only, and a design is resolved by name to
    ``<name>.png``."""
    if not filename:
        raise ListingDesignUploadRefused("the upload needs a filename")
    if filename != Path(filename).name:
        raise ListingDesignUploadRefused(f"{filename!r} is not a plain filename")
    stem = Path(filename).stem
    # `Path(".png").stem` is ".png": a dotfile, not a name.
    if not stem or stem.startswith("."):
        raise ListingDesignUploadRefused(f"{filename!r} has no name to save it under")

    try:
        with Image.open(BytesIO(payload)) as probe:
            kind = probe.format
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ListingDesignUploadRefused("that file is not a readable image") from exc
    if kind != "PNG":
        raise ListingDesignUploadRefused(
            f"designs must be PNG files, and {filename} is a {kind or 'different'} image"
        )

    name = _free_name(workspace, stem, payload)
    destination = workspace.design_file(name)
    if not destination.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(destination, payload)
    return name


def _free_name(workspace: Workspace, stem: str, payload: bytes) -> str:
    """``stem``, or the first ``stem-N`` that is free or already holds these
    exact bytes."""
    candidate, n = stem, 1
    while True:
        path = workspace.design_file(candidate)
        if not path.is_file() or path.read_bytes() == payload:
            return candidate
        n += 1
        candidate = f"{stem}-{n}"

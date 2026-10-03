"""Creating a listing: naming one is what writes it.

Both creation paths write through ``ListingDocuments.create``. The listings
editor creates through :func:`create_listing`. The ``new`` wizard builds its
stub with :func:`build_media_entries` for the template's kind and
:func:`build_listing_stub`, checks it with :func:`validate_listing_stub`, and
creates it directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidListing
from etsy_listings.core.config.errors import format_validation_error
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.media import MAX_IMAGES
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


def create_listing(
    workspace: Workspace, name: str, document: Mapping[str, Any]
) -> InvalidListing | None:
    """Write ``document`` as listing ``name``. Returns ``None`` once written.

    Holds ``name``'s lock, so a create and a rename to the same name cannot
    both win. Refusals, in order:

    * :class:`~etsy_listings.core.workspace.workspace.InvalidNameError`:
      ``name`` is not a single path segment (ADR-0013). Nothing is locked.
    * :class:`ListingNameTaken`: the **directory** exists, not just
      ``listing.yaml``. A ``listings/{name}/`` left with a lockfile and no
      document would hand the new listing another listing's remote ids.
    * :class:`InvalidListing`, returned rather than raised: ``document`` does
      not validate structurally. An *incomplete* document validates and is
      written (ADR-0043).
    """
    try:
        ListingDocuments(workspace).create(name, document)
    except ValidationError as exc:
        return InvalidListing.of(exc)
    return None


def load_template_kind(workspace: Workspace, template: str) -> str:
    """Which of the three kinds ``template`` is.

    ``new`` has to know: the shape of a valid ``media`` entry depends on it,
    and writing the wrong shape produces a listing that only fails later, at
    render time, with nothing pointing back at ``new``.
    """
    return workspace.load_template_config(template).kind


def build_media_entries(*, template: str, kind: str, colours: list[str]) -> list[dict[str, str]]:
    """The stub's ``media:``, which depends on the referenced template's kind.

    ``colour-matrix`` gets one entry per colour, each naming its colour --
    but capped at Etsy's 20-image limit, because a print provider can offer
    far more colours than Etsy accepts photos: Comfort Colors 1717 / Monster
    Digital offers 33, and one entry each is a listing Etsy will reject.
    Which 20 is genuinely arbitrary, so it is the first 20 in offer order and
    ``new`` says that it truncated. Every colour still appears in ``colors:``
    -- that decides which Printify variants sell, not which photos get
    rendered.

    ``multiple`` and ``single`` get exactly one entry and **no** ``colour``:
    each produces one output, so there is nothing to disambiguate.
    """
    if kind == "colour-matrix":
        return [{"template": template, "colour": colour} for colour in colours[:MAX_IMAGES]]
    return [{"template": template}]


def build_listing_stub(
    *,
    garment_profile_slug: str,
    design_ref: str,
    colours: list[str],
    pricing_plan_ref: str,
    brief: str,
    media: list[dict[str, str]],
) -> dict[str, Any]:
    """A starting ``listing.yaml`` document: prices come from the referenced
    pricing plan (per-size/per-colour adjustment is a manual edit), the media entries
    :func:`build_media_entries` decided, and blank
    title, description and tags -- ordinary editable values, nothing
    invented."""
    return {
        "garment_profile": garment_profile_slug,
        "design": design_ref,
        "colors": colours,
        "brief": brief,
        "pricing_plan": pricing_plan_ref,
        "prices": {},
        "etsy": {"title": "", "description": {}, "tags": []},
        "media": media,
    }


def validate_listing_stub(data: dict[str, Any], *, currency: str) -> Listing:
    try:
        return Listing.model_validate(data, context={"currency": currency})
    except ValidationError as exc:
        raise format_validation_error(Path("<new listing stub>"), exc) from exc

"""Creating a listing: naming one is what writes it.

Both creation paths write through ``ListingDocuments.create``. The listings
editor creates through :func:`create_listing`. The ``new`` wizard builds its
stub with :func:`build_media_entries` for the template's kind and
:class:`ListingStub`, checks it with :func:`validate_listing_stub`, and
creates it directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidListing
from etsy_listings.core.config.errors import format_validation_error
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.media import MAX_IMAGES
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace


def create_listing(
    workspace: Workspace, name: str, document: Mapping[str, Any]
) -> InvalidListing | None:
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
    return template_state(workspace, template).require().kind


def build_media_entries(*, template: str, kind: str, colours: list[str]) -> list[dict[str, str]]:
    if kind == "colour-matrix":
        return [{"template": template, "colour": colour} for colour in colours[:MAX_IMAGES]]
    return [{"template": template}]


@dataclass(frozen=True)
class ListingStub:
    garment_profile_slug: str
    design_ref: str
    colours: list[str]
    pricing_plan_ref: str
    brief: str
    media: list[dict[str, str]]

    def document(self) -> dict[str, Any]:
        return {
            "garment_profile": self.garment_profile_slug,
            "design": {"default": self.design_ref},
            "colors": self.colours,
            "brief": self.brief,
            "pricing_plan": self.pricing_plan_ref,
            "prices": {},
            "etsy": {"title": "", "description": {}, "tags": []},
            "media": self.media,
        }


def validate_listing_stub(data: dict[str, Any], *, currency: str) -> Listing:
    try:
        return Listing.model_validate(data, context={"currency": currency})
    except ValidationError as exc:
        raise format_validation_error(Path("<new listing stub>"), exc) from exc

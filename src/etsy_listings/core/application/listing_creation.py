"""Creating a listing: naming one is what writes it.

One persistence interpretation for both creation paths. The listings editor
creates through :func:`create_listing`; the ``new`` wizard builds its stub --
:func:`build_media_entries` for the template's kind, :func:`build_listing_stub`,
checked by :func:`validate_listing_stub` -- and writes it through
:func:`write_listing`, the step ``create_listing`` ends in.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidListing, ListingNameTaken
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.config.errors import format_validation_error
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.media import MAX_IMAGES
from etsy_listings.core.workspace.workspace import Workspace


def create_listing(
    workspace: Workspace, name: str, document: Mapping[str, Any], *, locks: WorkspaceLocks
) -> InvalidListing | None:
    """Write ``document`` as listing ``name``; ``None`` once written.

    Under ``name``'s write lock, so a create and a rename to the same name
    cannot both win. Refusals, in order:

    * :class:`~etsy_listings.core.workspace.workspace.InvalidNameError` --
      ``name`` is not a single path segment (ADR-0013); nothing is locked.
    * :class:`ListingNameTaken` -- the **directory** exists, not just
      ``listing.yaml``: a ``listings/{name}/`` left with a lockfile and no
      document would hand the new listing another one's remote ids.
    * :class:`InvalidListing`, returned -- ``document`` does not structurally
      validate. An *incomplete* document validates and is written (ADR-0043).
    """
    directory = workspace.listing_file(name).parent
    with locks.listing(name):
        if directory.exists():
            raise ListingNameTaken(name)
        try:
            Listing.model_validate(
                dict(document), context={"currency": workspace.defaults.etsy.currency}
            )
        except ValidationError as exc:
            return InvalidListing.of(exc)
        write_listing(workspace, name, dict(document))
    return None


def write_listing(workspace: Workspace, name: str, data: dict[str, Any]) -> Path:
    """Write a new ``listing.yaml``, refusing with :class:`FileExistsError`
    to overwrite one. Validation is the caller's: the wizard reports a
    malformed stub as a config error, the editor as field errors."""
    path = workspace.listing_file(name)
    if path.is_file():
        raise FileExistsError(f"a listing already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


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

"""Creating a listing: naming one is what writes it.

One persistence interpretation for both creation paths. The listings editor
creates through :func:`create_listing`; the ``new`` wizard builds its stub and
writes it through :func:`write_listing`, the step ``create_listing`` ends in.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidListing, ListingNameTaken
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.config.listing import Listing
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

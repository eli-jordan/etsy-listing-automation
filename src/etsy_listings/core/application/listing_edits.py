"""Editing a saved listing: the editor's patch, merged into the document.

Autosave makes concurrent edits ordinary. The editor saves each field as the
seller moves between them, and an AI run writes in the background.
``ListingDocuments.edit`` holds the listing's lock around the read, the merge
and the write, so two edits cannot lose one another. This module owns what a
patch means.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidListing
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.workspace.listing_documents import Document, ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


def edit_listing(
    workspace: Workspace,
    name: str,
    patch: Mapping[str, Any],
    *,
    batches: BatchStore,
) -> InvalidListing | None:
    """Merge ``patch`` into listing ``name`` and write it. Returns ``None``
    once written.

    Raises :class:`ListingMissing` when there is no listing to edit, whether
    before or after waiting for its lock. Returns :class:`InvalidListing`,
    writing nothing, when the merged document does not validate
    structurally. An incomplete one is written (ADR-0043).

    Cancelling a pending delete, by clearing ``lifecycle: deleted``, means the
    listing never went. The batch rows the delete marked therefore come back
    (ADR-0036; batch spec, rename and delete hooks).
    """
    before: Document = {}

    def merge(raw: Document) -> Document:
        before.update(raw)
        merged = _merge(raw, patch)
        Listing.model_validate(merged, context={"currency": workspace.defaults.etsy.currency})
        return merged

    try:
        merged = ListingDocuments(workspace).edit(name, merge)
    except ValidationError as exc:
        return InvalidListing.of(exc)
    assert merged is not None
    if before.get("lifecycle") == "deleted" and merged.get("lifecycle") != "deleted":
        design = merged.get("design")
        default = design.get("default") if isinstance(design, dict) else None
        batches.restore_listing(name, default)
    return None


def _merge(base: Document, patch: Mapping[str, Any]) -> Document:
    """A shallow merge, except for ``etsy:``, which merges one level deep.
    The editor's tabs each own a slice of it (title, tags, section, and so
    on), and a shallow overwrite there would let one tab's autosave silently
    erase whatever the last edit wrote to a sibling field. ``lifecycle:
    null`` deletes the key (Un-retire, Cancel) rather than writing
    ``active``."""
    merged = dict(base)
    for key, value in patch.items():
        if key == "etsy" and isinstance(value, dict) and isinstance(merged.get("etsy"), dict):
            merged["etsy"] = {**merged["etsy"], **value}
        elif key == "lifecycle" and value is None:
            merged.pop("lifecycle", None)
        else:
            merged[key] = value
    return merged

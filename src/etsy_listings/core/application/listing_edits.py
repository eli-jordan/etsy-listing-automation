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
    """Returns ``None`` once written, or :class:`InvalidListing`, writing
    nothing."""
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
    _restore_rows_if_undeleted(batches, name, before, merged)
    return None


def _restore_rows_if_undeleted(
    batches: BatchStore, name: str, before: Document, merged: Document
) -> None:
    """Cancelling a pending delete means the listing never went, so the batch
    rows the delete marked come back (ADR-0036)."""
    if before.get("lifecycle") == "deleted" and merged.get("lifecycle") != "deleted":
        design = merged.get("design")
        default = design.get("default") if isinstance(design, dict) else None
        batches.restore_listing(name, default)


_KEYS_A_NULL_REMOVES = frozenset({"lifecycle", "template_positions"})


def _merge(base: Document, patch: Mapping[str, Any]) -> Document:
    merged = dict(base)
    for key, value in patch.items():
        if key == "etsy" and isinstance(value, dict) and isinstance(merged.get("etsy"), dict):
            merged["etsy"] = {**merged["etsy"], **value}
        elif key in _KEYS_A_NULL_REMOVES and value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged

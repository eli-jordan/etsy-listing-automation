"""Editing a saved listing: read, merge, write, under its write lock.

Autosave makes concurrent edits ordinary -- the editor saves each field as
the seller moves between them, and an AI run writes in the background -- so
two read-merge-writes interleaved would silently lose the first. The lock is
held around the whole of it, and the listing re-checked once it is held: a
rename or delete that held the lock first may have moved it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml
from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidListing, ListingMissing
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.config.listing import Listing
from etsy_listings.core.workspace.atomic import write_yaml_atomic
from etsy_listings.core.workspace.workspace import Workspace


def edit_listing(
    workspace: Workspace,
    name: str,
    patch: Mapping[str, Any],
    *,
    locks: WorkspaceLocks,
    batches: BatchStore,
) -> InvalidListing | None:
    """Merge ``patch`` into listing ``name`` and write it; ``None`` once
    written.

    Raises :class:`ListingMissing` when there is no listing to edit, before
    or after waiting for its lock. Returns :class:`InvalidListing`, writing
    nothing, when the merged document does not structurally validate; an
    incomplete one is written (ADR-0043).

    Cancelling a pending delete -- ``lifecycle: deleted`` cleared -- means the
    listing never went, so the batch rows the delete marked come back
    (ADR-0036; batch spec, rename and delete hooks).
    """
    path = workspace.listing_file(name)
    with locks.listing(name):
        if not path.is_file():
            raise ListingMissing(name)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        merged = _merge(raw, patch)
        try:
            Listing.model_validate(merged, context={"currency": workspace.defaults.etsy.currency})
        except ValidationError as exc:
            return InvalidListing.of(exc)
        write_yaml_atomic(path, merged)
    if raw.get("lifecycle") == "deleted" and merged.get("lifecycle") != "deleted":
        design = merged.get("design")
        default = design.get("default") if isinstance(design, dict) else None
        batches.restore_listing(name, default)
    return None


def _merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """A shallow merge, except ``etsy:``, which merges one level deep -- the
    editor's tabs each own a slice of it (title, tags, section, ...) and a
    shallow overwrite there would let one tab's autosave silently erase
    whatever the last edit wrote to a sibling field. ``lifecycle: null``
    deletes the key (Un-retire, Cancel) rather than writing ``active``."""
    merged = dict(base)
    for key, value in patch.items():
        if key == "etsy" and isinstance(value, dict) and isinstance(merged.get("etsy"), dict):
            merged["etsy"] = {**merged["etsy"], **value}
        elif key == "lifecycle" and value is None:
            merged.pop("lifecycle", None)
        else:
            merged[key] = value
    return merged

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from etsy_listings.core.ai import ProposalStore
from etsy_listings.core.workspace.listing_documents import (
    ListingDocuments,
    ListingMissingError,
    ListingNameTakenError,
)
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.workspace import Workspace


def move_listing(workspace: Workspace, old: str, new: str) -> None:
    """Move listing ``old``, whole, to ``new``.

    The directory move carries ``listing.yaml``, ``state.lock.json`` and the
    generated copy. The caches and the proposal move beside it. Leftover
    caches already at ``new`` belong to no listing, since ``new`` is free, so
    they are replaced. The lockfile's ``outputs`` keys still spell the old
    path afterwards, deliberately. Nothing reads them, the next apply makes
    them true again, and rewriting them here would breach "only the lockfile
    merges a lockfile".

    Raises :class:`ListingMissingError`, also after waiting for the lock, and
    :class:`ListingNameTakenError` when ``new`` is not free.
    """
    documents = ListingDocuments(workspace)
    with documents.lock(old, new):
        if not documents.exists(old):
            raise ListingMissingError(old)
        if not documents.is_free(new):
            raise ListingNameTakenError(new)
        for path_of in _KEYED_PATHS:
            source, target = path_of(workspace, old), path_of(workspace, new)
            if not source.exists():
                continue
            if target.is_dir():
                remove_tree(target)
            source.replace(target)
        ProposalStore(workspace).move(old, new)


def remove_listing(workspace: Workspace, name: str) -> None:
    """Wipe listing ``name`` and everything keyed by it. Designs, garment
    profiles and pricing plans stay, because they are reusable."""
    with ListingDocuments(workspace).lock(name):
        for path_of in _KEYED_PATHS:
            path = path_of(workspace, name)
            if path.is_dir():
                remove_tree(path)
            else:
                path.unlink(missing_ok=True)
        ProposalStore(workspace).remove(name)


def discard_research(workspace: Workspace, name: str) -> None:
    """Remove ``name``'s market snapshot and proposal and leave the listing.
    A delete pending its remote retraction (ADR-0035) does this, because
    the seller has finished researching the listing."""
    with ListingDocuments(workspace).lock(name):
        workspace.market_snapshot_file(name).unlink(missing_ok=True)
        ProposalStore(workspace).remove(name)


_KEYED_PATHS: tuple[Callable[[Workspace, str], Path], ...] = (
    Workspace.listing_dir,
    Workspace.renders_dir,
    Workspace.preview_dir,
    Workspace.market_snapshot_file,
)
"""The listing's own paths. The proposal is not one: its record names its
listing, so :class:`ProposalStore` moves it."""

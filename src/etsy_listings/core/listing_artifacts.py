from __future__ import annotations

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
        for source, target in zip(_keyed(workspace, old), _keyed(workspace, new), strict=True):
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
        for path in _keyed(workspace, name):
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


def _keyed(workspace: Workspace, name: str) -> tuple[Path, ...]:
    """The listing's own paths, in a fixed order so a move can pair old with
    new. The listing directory comes first. The proposal is not in this
    list: its store moves it, because the record names its listing."""
    return (
        workspace.listing_dir(name),
        workspace.renders_dir(name),
        workspace.preview_dir(name),
        workspace.market_snapshot_file(name),
    )

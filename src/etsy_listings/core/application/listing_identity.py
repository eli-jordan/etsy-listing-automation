"""Renaming and deleting a listing: the operations that change what a
listing name refers to.

A listing's identity is its directory name. ``core/listing_artifacts.py``
moves and removes what the workspace keys by that name. This module adds the
application state keyed by it, which is the listing's batch rows and its AI
run (batch spec, rename and delete hooks), and the rules about when a delete
is allowed at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.application.refusals import ListingMissing, PublishedListingDeletion
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.engine.status import is_live_etsy_state, remote_ids
from etsy_listings.core.listing_artifacts import discard_research, move_listing, remove_listing
from etsy_listings.core.workspace.listing_documents import Document, ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class Deletion:
    """What a delete did. ``wiped`` means the listing had no remotes and is
    gone. Otherwise it is marked ``lifecycle: deleted`` and stays, pending the
    apply that retracts its remotes. ``etsy_state`` is what Etsy said when
    the delete was allowed."""

    wiped: bool
    etsy_state: str | None


def rename_listing(
    workspace: Workspace,
    old: str,
    new: str,
    *,
    batches: BatchStore,
    ai_runs: AiRunRegistry,
) -> None:
    """Move listing ``old``, whole, to ``new`` (``listing_artifacts.move_listing``).
    Every batch row naming ``old`` follows, and ``old``'s finished AI run is
    forgotten.

    Renaming to the same name changes nothing, since the editor commits an
    unchanged name on every blur. Refusals: :class:`ListingMissing` (also
    after waiting for the lock), ``InvalidNameError`` for a ``new`` that is
    not a path segment, and :class:`ListingNameTaken` for a directory already
    at ``new``.
    """
    documents = ListingDocuments(workspace)
    if not documents.exists(old):
        raise ListingMissing(old)
    workspace.listing_dir(new)
    if new == old:
        return
    # The batch locks come first, in the order creating a batch row takes
    # them. See `BatchStore.following_rename`.
    with batches.following_rename(old, new):
        move_listing(workspace, old, new)
    ai_runs.forget(old)


def delete_listing(
    workspace: Workspace,
    name: str,
    *,
    batches: BatchStore,
    ai_runs: AiRunRegistry,
    etsy_states: EtsyStates,
) -> Deletion:
    """Delete listing ``name`` (ADR-0035).

    A listing published on Etsy is refused with
    :class:`PublishedListingDeletion` before anything changes; it should be
    retired instead. A listing with no remotes is wiped now. A listing with
    remotes is marked ``lifecycle: deleted`` and left pending. Its market
    snapshot and proposal go now all the same, because the seller has
    finished researching it.

    Either way, its batch rows are marked deleted first, so the queue cannot
    start one between the stop and the delete. Its active AI run is then
    asked to stop, so it writes no proposal for a listing being deleted, and
    is forgotten. Raises :class:`ListingMissing` when there is no listing,
    whether before or after waiting for its lock.
    """
    documents = ListingDocuments(workspace)
    if not documents.exists(name):
        raise ListingMissing(name)
    etsy_listing_id, printify_product_id = remote_ids(workspace, name)
    etsy_state = (
        etsy_states([etsy_listing_id]).get(etsy_listing_id) if etsy_listing_id is not None else None
    )
    if is_live_etsy_state(etsy_state):
        raise PublishedListingDeletion(name)
    batches.mark_deleted(name)
    run = ai_runs.latest(name)
    if run is not None:
        run.request_stop("cancelled")
    ai_runs.forget(name)
    with documents.lock(name):
        if etsy_listing_id is None and printify_product_id is None:
            if not documents.exists(name):
                raise ListingMissing(name)
            remove_listing(workspace, name)
            return Deletion(wiped=True, etsy_state=etsy_state)
        documents.edit(name, _mark_deleted)
        discard_research(workspace, name)
    return Deletion(wiped=False, etsy_state=etsy_state)


def _mark_deleted(raw: Document) -> Document:
    return {**raw, "lifecycle": "deleted"}

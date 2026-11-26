from __future__ import annotations

from dataclasses import dataclass

from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.application.refusals import (
    ListingMissingError,
    PublishedListingDeletionError,
)
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.engine.status import is_live_etsy_state, remote_ids
from etsy_listings.core.listing_artifacts import discard_research, move_listing, remove_listing
from etsy_listings.core.workspace.listing_documents import Document, ListingDocuments
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class Deletion:
    """Not ``wiped``: the listing had remotes, so it stays marked
    ``lifecycle: deleted`` until an apply retracts them."""

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
    documents = ListingDocuments(workspace)
    if not documents.exists(old):
        raise ListingMissingError(old)
    workspace.listing_dir(new)
    if new == old:
        return
    # Batch locks first, in batch-row creation's order (`BatchStore.following_rename`).
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
    documents = ListingDocuments(workspace)
    if not documents.exists(name):
        raise ListingMissingError(name)
    etsy_listing_id, printify_product_id = remote_ids(workspace, name)
    etsy_state = (
        etsy_states([etsy_listing_id]).get(etsy_listing_id) if etsy_listing_id is not None else None
    )
    if is_live_etsy_state(etsy_state):
        raise PublishedListingDeletionError(name)
    # Before the stop, or the queue could start a row between the stop and the delete.
    batches.mark_deleted(name)
    run = ai_runs.latest(name)
    if run is not None:
        run.request_stop("cancelled")
    ai_runs.forget(name)
    with documents.lock(name):
        if etsy_listing_id is None and printify_product_id is None:
            if not documents.exists(name):
                raise ListingMissingError(name)
            remove_listing(workspace, name)
            return Deletion(wiped=True, etsy_state=etsy_state)
        documents.edit(name, _mark_deleted)
        discard_research(workspace, name)
    return Deletion(wiped=False, etsy_state=etsy_state)


def _mark_deleted(raw: Document) -> Document:
    return {**raw, "lifecycle": "deleted"}

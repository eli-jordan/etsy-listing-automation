"""Renaming and deleting a listing: the operations that change what a
listing name refers to, and so must carry everything keyed by it.

A listing's identity is its directory name. Its render cache, market
snapshot, cached AI proposal (ADR-0049), batch rows and AI run are all keyed
by that name too, so each follows a rename and goes with a delete
(market-seo spec, *Cache*; batch spec, rename and delete hooks) -- left
behind, a new listing given the name would inherit them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import yaml

from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.dependencies import EtsyStates, ListingAiRuns
from etsy_listings.core.application.refusals import (
    ListingMissing,
    ListingNameTaken,
    PublishedListingDeletion,
)
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.engine.status import is_live_etsy_state, remote_ids
from etsy_listings.core.workspace.atomic import write_yaml_atomic
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class Deletion:
    """What a delete did. ``wiped``: the listing had no remotes and is gone.
    Otherwise it is marked ``lifecycle: deleted`` and stays, pending the
    apply that retracts its remotes. ``etsy_state`` is what Etsy said when
    the delete was allowed."""

    wiped: bool
    etsy_state: str | None


def rename_listing(
    workspace: Workspace,
    old: str,
    new: str,
    *,
    locks: WorkspaceLocks,
    batches: BatchStore,
    proposals: ProposalStore,
    ai_runs: ListingAiRuns,
) -> None:
    """Move listing ``old``, whole, to ``new``.

    ``listing.yaml``, ``state.lock.json`` and generated copy travel in the
    directory move; the render cache, market snapshot and proposal move
    beside it; every batch row naming ``old`` follows, and ``old``'s finished
    AI run is forgotten. The lockfile's ``outputs`` keys still spell the old
    path afterwards, deliberately: nothing reads them, the next apply makes
    them true again, and rewriting them here would breach "only the lockfile
    merges a lockfile".

    Renaming to the same name changes nothing -- the editor commits an
    unchanged name on every blur. Refusals: :class:`ListingMissing` (also
    after waiting for the lock), ``InvalidNameError`` for a ``new`` that is
    not a path segment, :class:`ListingNameTaken` for a directory already at
    ``new``.
    """
    _require(workspace, old)
    destination = workspace.listing_dir(new)
    if new == old:
        return
    # The batch locks come first -- the order creating a batch row takes them
    # in -- see `BatchStore.following_rename`.
    with batches.following_rename(old, new), locks.listing(old, new):
        _require(workspace, old)
        if destination.exists():
            raise ListingNameTaken(new)
        workspace.listing_dir(old).rename(destination)
        renders = workspace.renders_dir(old)
        if renders.is_dir():
            renders.rename(workspace.renders_dir(new))
        snapshot = workspace.market_snapshot_file(old)
        if snapshot.is_file():
            os.replace(snapshot, workspace.market_snapshot_file(new))
        proposals.move(old, new)
    ai_runs.forget(old)


def delete_listing(
    workspace: Workspace,
    name: str,
    *,
    locks: WorkspaceLocks,
    batches: BatchStore,
    proposals: ProposalStore,
    ai_runs: ListingAiRuns,
    etsy_states: EtsyStates,
) -> Deletion:
    """Delete listing ``name`` (ADR-0035).

    Published on Etsy: refused with :class:`PublishedListingDeletion` before
    anything changes -- retire it instead. No remotes: wiped now. Remotes:
    marked ``lifecycle: deleted`` and left pending; its market snapshot and
    proposal go now all the same, since the seller is done researching it.

    Either way its batch rows are marked deleted first, so the queue cannot
    start one between the stop and the delete; its active AI run is then
    asked to stop, so it writes no proposal for a listing being deleted, and
    forgotten. Raises :class:`ListingMissing` when there is no listing,
    before or after waiting for its lock.
    """
    _require(workspace, name)
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
    with locks.listing(name):
        _require(workspace, name)
        if etsy_listing_id is None and printify_product_id is None:
            workspace.remove_listing(name)
            return Deletion(wiped=True, etsy_state=etsy_state)
        path = workspace.listing_file(name)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw["lifecycle"] = "deleted"
        write_yaml_atomic(path, raw)
        workspace.market_snapshot_file(name).unlink(missing_ok=True)
        proposals.remove(name)
    return Deletion(wiped=False, etsy_state=etsy_state)


def _require(workspace: Workspace, name: str) -> None:
    if not workspace.listing_file(name).is_file():
        raise ListingMissing(name)

"""Which listings a batch deploy takes (ADR-0059): the batch's reviewed rows
whose listing has changes its last apply did not deploy, in row order."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.core.application.batch_workflow import batch_deploy_listings, deployable
from etsy_listings.core.application.refusals import BatchMissingError, NothingToDeployError
from etsy_listings.core.batches import BatchStore
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import copy_listing
from tests.support.listings import applied, batch_naming, batch_rows


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    for name in ("never-applied", "deployed", "edited", "unreviewed", "drafting", "gone"):
        copy_listing(workspace_root, name)
    return Workspace.discover(root_override=workspace_root)


def _batch(workspace: Workspace) -> BatchStore:
    store = batch_naming(
        workspace, "b1", "never-applied", "deployed", "edited", "unreviewed", "drafting", "gone"
    )
    applied(workspace, "deployed")
    applied(workspace, "edited")
    listing = workspace.listing_file("edited")
    stamp = workspace.lock_file("edited").stat().st_mtime + 10
    os.utime(listing, (stamp, stamp))
    batch = store.load("b1")
    assert batch is not None
    for index, row in enumerate(batch.rows):
        batch.rows[index] = row.model_copy(
            update={
                "reviewed": row.name != "unreviewed",
                "ai": "running" if row.name == "drafting" else row.ai,
                "deleted": row.name == "gone",
            }
        )
    store.save(batch)
    return store


def test_a_batch_deploy_takes_reviewed_rows_with_undeployed_changes_in_row_order(
    workspace: Workspace,
) -> None:
    store = _batch(workspace)

    assert batch_deploy_listings(workspace, store, "b1") == ("never-applied", "edited")
    assert [row.name for row in batch_rows(store, "b1") if deployable(workspace, row)] == [
        "never-applied",
        "edited",
    ]


def test_a_batch_with_nothing_to_deploy_is_refused(workspace: Workspace) -> None:
    store = batch_naming(workspace, "b1", "deployed")
    applied(workspace, "deployed")

    with pytest.raises(NothingToDeployError, match="no reviewed listings with changes"):
        batch_deploy_listings(workspace, store, "b1")
    with pytest.raises(BatchMissingError):
        batch_deploy_listings(workspace, store, "nope")

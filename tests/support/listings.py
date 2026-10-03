"""What a direct listing-operation test injects in place of the UI process's
coordinators (module-structure plan, PR 6).

The write locks are the real ``WorkspaceLocks`` -- competing writes are only
proved against the lock that serialises them -- and so is the AI run
registry, core's own since PR 9. The Etsy state memo is replaced: only Etsy
knows a listing's state.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etsy_listings.core.application.ai.registry import AiRun, AiRunRegistry
from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.batches import Batch, BatchRow, BatchStore
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, a_lock

CREATED = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)


def ai_run(listing: str, *, finished: bool = False) -> tuple[AiRunRegistry, AiRun]:
    """A registry holding one run for ``listing``, never started on a
    thread: still running, or finished ``done``."""
    registry = AiRunRegistry()
    run = registry.create(listing, draft_brief=False)
    assert isinstance(run, AiRun)
    if finished:
        run.finish("done")
    return registry, run


def etsy_reports(states: Mapping[int, str] | None = None) -> EtsyStates:
    """An Etsy that answers ``states`` and knows nothing else -- the
    "no credentials" answer when ``states`` is empty."""
    known = dict(states or {})

    def lookup(listing_ids: Sequence[int]) -> dict[int, str | None]:
        return {listing_id: known.get(listing_id) for listing_id in listing_ids}

    return lookup


def applied(
    workspace: Workspace,
    name: str = FIXTURE_LISTING,
    *,
    etsy_listing_id: int | None = None,
    product_id: str | None = None,
) -> Path:
    """Leave ``name`` as an apply would have: its remote ids recorded and a
    stage completed. ``listing.yaml`` is aged so it reads as unedited since."""
    remote: dict[str, Any] = {}
    if etsy_listing_id is not None:
        remote["etsy_listing_id"] = etsy_listing_id
    if product_id is not None:
        remote["printify_product_id"] = product_id
    path = workspace.lock_file(name)
    a_lock(remote=remote, stages_completed=["render"]).write(path)
    listing = workspace.listing_file(name)
    stamp = path.stat().st_mtime - 10
    os.utime(listing, (stamp, stamp))
    return path


def batch_naming(workspace: Workspace, batch_id: str, *listings: str) -> BatchStore:
    """A batch with one created row per listing, its design the listing's
    own name -- as confirming a staging session leaves it."""
    store = BatchStore(workspace)
    store.save(
        Batch(
            id=batch_id,
            listing_template="heavyweight-tee",
            template={},
            template_saved_at=CREATED,
            label=batch_id,
            created_at=CREATED,
            rows=[
                BatchRow(
                    id=f"row-{name}",
                    sha256="0" * 64,
                    sources=[f"{name}.png"],
                    base=name,
                    name=name,
                    creation="created",
                    ai="done",
                    design=name,
                )
                for name in listings
            ],
        )
    )
    return store


def batch_rows(store: BatchStore, batch_id: str) -> list[BatchRow]:
    batch = store.load(batch_id)
    assert batch is not None
    return batch.rows

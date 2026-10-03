"""What a direct listing-operation test injects in place of the UI process's
coordinators (module-structure plan, PR 6).

The write locks are the real ``WorkspaceLocks`` -- competing writes are only
proved against the lock that serialises them. The AI run registry and the
Etsy state memo are replaced: an operation asks them two questions each, and
a test cares only about what it asked.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etsy_listings.core.application.dependencies import EtsyStates
from etsy_listings.core.batches import Batch, BatchRow, BatchStore
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, a_lock

CREATED = datetime(2026, 9, 27, 11, 42, tzinfo=UTC)


@dataclass
class RecordingRun:
    """An AI run that only remembers being asked to stop."""

    stops: list[str] = field(default_factory=list)

    def request_stop(self, reason: str) -> bool:
        self.stops.append(reason)
        return True


@dataclass
class RecordingAiRuns:
    """The AI run registry as a listing operation sees it."""

    runs: dict[str, RecordingRun] = field(default_factory=dict)
    forgotten: list[str] = field(default_factory=list)

    @classmethod
    def running(cls, *listings: str) -> RecordingAiRuns:
        return cls(runs={listing: RecordingRun() for listing in listings})

    def latest(self, listing: str) -> RecordingRun | None:
        return self.runs.get(listing)

    def forget(self, listing: str) -> None:
        self.forgotten.append(listing)


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

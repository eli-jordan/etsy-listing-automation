"""A full apply marks the listing's batch row reviewed (spec, *Review
workflow*, *Deployment interaction*).

Deploying a draft is the seller's judgement that it is finished, so the
batch summary need not be told again. The rule sits beside the proposal
cleanup in ``engine/run.py``, under the same *full success* test
(``tests/core/behaviour/test_proposal_cleanup.py``), so a CLI apply and a UI
apply mark it alike. An apply that blocked a stage deployed nothing there,
and leaves the row as it was.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from etsy_listings.core.batches import Batch, BatchRow, BatchStore
from etsy_listings.core.engine.run import apply_listings
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context
from tests.support.pipeline import a_deployable_context, real_stages


def _batch(workspace: Workspace) -> BatchStore:
    store = BatchStore(workspace)
    store.save(
        Batch(
            id="b1",
            listing_template="heavyweight-tee",
            template={},
            template_saved_at=datetime(2026, 11, 23, tzinfo=UTC),
            label="b1",
            created_at=datetime(2026, 11, 23, tzinfo=UTC),
            rows=[
                BatchRow(
                    id="row-1",
                    sha256="0" * 64,
                    sources=[f"{LISTING}.png"],
                    base=LISTING,
                    name=LISTING,
                    design=LISTING,
                    creation="created",
                    ai="done",
                )
            ],
        )
    )
    return store


def _reviewed(store: BatchStore) -> bool:
    batch = store.load("b1")
    assert batch is not None
    return batch.rows[0].reviewed


def test_a_full_apply_marks_the_listing_s_batch_row_reviewed(workspace_root: Path) -> None:
    ctx = a_deployable_context(workspace_root)
    store = _batch(ctx.workspace)

    report = apply_listings(ctx, [LISTING], real_stages())

    assert report.outcomes[0].ok, report.outcomes[0].error
    assert _reviewed(store)


def test_an_apply_with_blocked_stages_leaves_the_row_unreviewed(workspace_root: Path) -> None:
    """No shop: the render runs, every remote stage is blocked."""
    ctx = a_context(workspace_root)
    store = _batch(ctx.workspace)

    report = apply_listings(ctx, [LISTING], list(STAGES))

    assert report.outcomes[0].ok, report.outcomes[0].error
    assert not _reviewed(store)

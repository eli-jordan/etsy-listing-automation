"""A20: how a stage hands back the ids an API gave it.

Until Phase 2 no stage produced one, so ``apply`` copied ``lock.remote``
through untouched and there was no channel at all. ``printify_product`` is the
first stage that has to write one -- the product id it just created is the
only thing standing between a re-run and a duplicate product (PRD 48).

The engine merges; the stage returns a value and does not touch the lockfile.
That is the same rule ``applied`` and ``outputs`` already follow, and it is
what keeps a stage testable without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, StageState
from etsy_listings.engine.stage import StageApplyResult

from tests.support.builders import a_context, a_lock


@dataclass
class RecordingStage:
    """A stage that reports exactly what it is told to, and nothing else."""

    name: str = "printify_product"
    local: bool = False
    applied: dict[str, Any] | None = None
    outputs: dict[str, str] | None = None
    remote: dict[str, Any] | None = None
    seen_remote: dict[str, Any] | None = None
    """Filled in by ``apply`` with the ``lock.remote`` it was actually handed
    -- the seam A26's threading is tested through."""
    seen_applied: dict[str, Any] | None = None
    """Filled in by ``apply`` with the ``lock.applied`` it was actually
    handed, to prove threading ``remote`` live does not also thread
    ``applied``."""

    def desired(self, ctx: RunContext, listing: str) -> dict[str, Any]:
        return {"desired": True}

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile) -> None:
        return None

    def plan(self, desired: Any, applied: Any, live: Any) -> StagePlan:
        return StagePlan(stage=self.name, will_run=True)

    def apply(
        self,
        ctx: RunContext,
        stage_plan: StagePlan,
        desired: Any,
        live: Any,
        lock: Lockfile,
    ) -> StageApplyResult:
        self.seen_remote = dict(lock.remote)
        self.seen_applied = dict(lock.applied)
        return StageApplyResult(
            applied=self.applied if self.applied is not None else {"ok": True},
            outputs=self.outputs or {},
            remote=self.remote or {},
        )


def _run(*stages: RecordingStage, lock: Lockfile, root: Path) -> Lockfile:
    ctx = a_context(root)
    stage_plans = tuple(StagePlan(stage=stage.name, will_run=True) for stage in stages)
    planned = PlannedRun(
        plan=Plan(
            listing="take-a-hike",
            is_live=False,
            etsy_listing_id=None,
            stage_plans=stage_plans,
        ),
        states=tuple(
            StageState(
                stage=stage,  # type: ignore[arg-type]
                desired={"desired": True},
                applied=None,
                live=None,
                stage_plan=stage_plan,
            )
            for stage, stage_plan in zip(stages, stage_plans, strict=True)
        ),
    )
    return execute(ctx, planned, lock)


def test_a_stage_can_report_a_remote_id(workspace_root: Path) -> None:
    stage = RecordingStage(remote={"printify_product_id": "6a9ffdbfecfdc9324d023442"})

    result = _run(stage, lock=a_lock(), root=workspace_root)

    assert result.remote["printify_product_id"] == "6a9ffdbfecfdc9324d023442"


def test_remote_ids_merge_rather_than_replace(workspace_root: Path) -> None:
    """Each stage owns its own key prefix. A Printify id arriving must not
    take the Etsy listing id with it."""
    stage = RecordingStage(remote={"printify_product_id": "new-id"})
    lock = a_lock(remote={"etsy_listing_id": 1234567890, "etsy_listing_state": "draft"})

    result = _run(stage, lock=lock, root=workspace_root)

    assert result.remote == {
        "etsy_listing_id": 1234567890,
        "etsy_listing_state": "draft",
        "printify_product_id": "new-id",
    }


def test_a_stage_that_reports_nothing_leaves_remote_alone(workspace_root: Path) -> None:
    """The Phase 0/1 behaviour, which must not change: `render` returns no
    remote state and the block it never touches survives untouched."""
    lock = a_lock(remote={"etsy_listing_id": 42})

    result = _run(RecordingStage(), lock=lock, root=workspace_root)

    assert result.remote == {"etsy_listing_id": 42}


def test_a_later_run_overwrites_the_key_it_owns(workspace_root: Path) -> None:
    lock = a_lock(remote={"printify_product_id": "old-id"})

    result = _run(
        RecordingStage(remote={"printify_product_id": "new-id"}), lock=lock, root=workspace_root
    )

    assert result.remote["printify_product_id"] == "new-id"


def test_remote_state_stays_out_of_the_input_hash(workspace_root: Path) -> None:
    """The invariant this whole channel exists to respect: a remote id is
    volatile, so it must never reach a hash. Two runs differing only in the
    id Printify handed back have to compare equal, or every listing shows a
    spurious diff forever."""
    with_id = _run(
        RecordingStage(remote={"printify_product_id": "a"}), lock=a_lock(), root=workspace_root
    )
    with_other = _run(
        RecordingStage(remote={"printify_product_id": "b"}), lock=a_lock(), root=workspace_root
    )

    assert with_id.input_hash() == with_other.input_hash()


# ------------------------------------------------------- threaded within a run (A26)


def test_a_remote_id_minted_this_run_is_visible_to_the_next_stages_apply(
    workspace_root: Path,
) -> None:
    """The case A26 exists for: a first `apply` that creates a Printify
    product, publishes it, and patches the resulting Etsy listing must not
    need running twice. `publish` mints the listing id in its own `apply`;
    `etsy_listing`'s `apply`, later in the same run, has to see it via
    `lock.remote` even though the lockfile on disk never had it."""
    publish = RecordingStage(name="publish", remote={"etsy_listing_id": 4572550919})
    etsy_listing = RecordingStage(name="etsy_listing")

    _run(publish, etsy_listing, lock=a_lock(), root=workspace_root)

    assert etsy_listing.seen_remote == {"etsy_listing_id": 4572550919}


def test_a_stages_own_applied_document_is_still_from_before_this_run(
    workspace_root: Path,
) -> None:
    """The other half of A26: threading `remote` live must not also thread
    `applied` -- stage order must not change what `lock.applied` says, only
    ids handed back by an API this run. The first stage's own `apply` result
    is folded into the *returned* lockfile (that always happened), but the
    second stage must not see it arrive early through `lock`."""
    lock = a_lock(applied={"publish": {"sync_flags": {}}})
    first = RecordingStage(name="publish", applied={"sync_flags": {"variants": True}})
    second = RecordingStage(name="etsy_listing")

    _run(first, second, lock=lock, root=workspace_root)

    assert second.seen_applied == {"publish": {"sync_flags": {}}}, (
        "second stage must see the pre-run applied document, not the first "
        "stage's freshly folded one"
    )

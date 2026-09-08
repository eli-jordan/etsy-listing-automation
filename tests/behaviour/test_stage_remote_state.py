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

from etsy_listings import __about__
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stage import StageApplyResult
from etsy_listings.workspace.workspace import Workspace


@dataclass
class RecordingStage:
    """A stage that reports exactly what it is told to, and nothing else."""

    name: str = "printify_product"
    local: bool = False
    applied: dict[str, Any] | None = None
    outputs: dict[str, str] | None = None
    remote: dict[str, Any] | None = None

    def desired(self, ctx: RunContext, listing: str) -> dict[str, Any]:
        return {"desired": True}

    def last_applied(self, lock: Lockfile) -> dict[str, Any] | None:
        return lock.applied.get(self.name)

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile) -> None:
        return None

    def plan(self, desired: Any, applied: Any, live: Any) -> StagePlan:
        return StagePlan(stage=self.name, will_run=True)

    def apply(
        self, ctx: RunContext, stage_plan: StagePlan, desired: Any, lock: Lockfile
    ) -> StageApplyResult:
        return StageApplyResult(
            applied=self.applied if self.applied is not None else {"ok": True},
            outputs=self.outputs or {},
            remote=self.remote or {},
        )


def _lock(**kwargs: Any) -> Lockfile:
    return Lockfile(tool_version=__about__.VERSION, applied_at="2026-09-08T00:00:00Z", **kwargs)


def _run(stage: RecordingStage, lock: Lockfile, root: Path) -> Lockfile:
    ctx = RunContext(workspace=Workspace.discover(root_override=root), catalog=None)  # type: ignore[arg-type]
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(StagePlan(stage=stage.name, will_run=True),),
    )
    return execute(ctx, plan, lock, [stage])  # type: ignore[list-item]


def test_a_stage_can_report_a_remote_id(workspace_root: Path) -> None:
    stage = RecordingStage(remote={"printify_product_id": "6a9ffdbfecfdc9324d023442"})

    result = _run(stage, _lock(), workspace_root)

    assert result.remote["printify_product_id"] == "6a9ffdbfecfdc9324d023442"


def test_remote_ids_merge_rather_than_replace(workspace_root: Path) -> None:
    """Each stage owns its own key prefix. A Printify id arriving must not
    take the Etsy listing id with it."""
    stage = RecordingStage(remote={"printify_product_id": "new-id"})
    lock = _lock(remote={"etsy_listing_id": 1234567890, "etsy_listing_state": "draft"})

    result = _run(stage, lock, workspace_root)

    assert result.remote == {
        "etsy_listing_id": 1234567890,
        "etsy_listing_state": "draft",
        "printify_product_id": "new-id",
    }


def test_a_stage_that_reports_nothing_leaves_remote_alone(workspace_root: Path) -> None:
    """The Phase 0/1 behaviour, which must not change: `render` returns no
    remote state and the block it never touches survives untouched."""
    lock = _lock(remote={"etsy_listing_id": 42})

    result = _run(RecordingStage(), lock, workspace_root)

    assert result.remote == {"etsy_listing_id": 42}


def test_a_later_run_overwrites_the_key_it_owns(workspace_root: Path) -> None:
    lock = _lock(remote={"printify_product_id": "old-id"})

    result = _run(RecordingStage(remote={"printify_product_id": "new-id"}), lock, workspace_root)

    assert result.remote["printify_product_id"] == "new-id"


def test_remote_state_stays_out_of_the_input_hash(workspace_root: Path) -> None:
    """The invariant this whole channel exists to respect: a remote id is
    volatile, so it must never reach a hash. Two runs differing only in the
    id Printify handed back have to compare equal, or every listing shows a
    spurious diff forever."""
    with_id = _run(RecordingStage(remote={"printify_product_id": "a"}), _lock(), workspace_root)
    with_other = _run(RecordingStage(remote={"printify_product_id": "b"}), _lock(), workspace_root)

    assert with_id.input_hash() == with_other.input_hash()

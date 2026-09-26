"""A29: a failed apply keeps what it did.

``execute`` used to fold every stage's result into a lockfile that only
``apply_listings`` wrote -- once, after the whole loop returned. A stage
raising partway through left every earlier stage's work unrecorded, so a
first `apply` that created a Printify product and then failed patching the
Etsy listing looked, to the next `plan`, exactly like a listing that had
never been touched. PRD 48's duplicate-create guard then refuses the
re-create, and no re-run can get past it.

``execute`` now takes a ``record`` callback and calls it with the stamped,
folded lockfile after every stage that succeeds -- and once more, marked
incomplete, when a stage raises, before re-raising. ``apply_listings``
supplies the one that writes ``state.lock.json``, so a partial apply is
durable through a crash rather than only through a clean return.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import IncompleteApply, Lockfile
from etsy_listings.engine.plan import PlannedRun, StageState
from etsy_listings.engine.run import apply_listings
from etsy_listings.engine.stage import StageApplyResult
from etsy_listings.errors import UserFacingError

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock


class _AppliedDoc(BaseModel):
    """A stand-in applied document, this file's own -- the rule under test is
    `execute`'s recording, not any real stage's document shape."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = True


@dataclass
class _Stage:
    """A stage that reports whatever it is told to, and raises on request.

    Implements the full `Stage` protocol (not just `apply`) so it can be
    driven either directly through `execute` with a hand-built `PlannedRun`
    (the way `test_stage_remote_state.py` does), or through `apply_listings`,
    which calls `desired`/`read_live`/`plan` for real via `build_plan`.
    """

    name: str
    local: bool = True
    group: str | None = None
    applied_model: type[_AppliedDoc] = _AppliedDoc
    remote: dict[str, Any] = field(default_factory=dict)
    fails: bool = False

    def desired(self, ctx: RunContext, listing: str, applied: _AppliedDoc | None) -> dict[str, Any]:
        return {"stage": self.name}

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: _AppliedDoc | None
    ) -> None:
        return None

    def plan(self, desired: Any, applied: Any, live: Any) -> Verdict:
        return Verdict.work(f"{self.name} has work to do")

    def apply(
        self,
        ctx: RunContext,
        desired: Any,
        applied: Any,
        live: Any,
        lock: Lockfile,
    ) -> StageApplyResult:
        if self.fails:
            raise UserFacingError(f"{self.name} refused")
        return StageApplyResult(applied={"ok": True}, remote=self.remote)


def _planned(*stages: _Stage) -> PlannedRun:
    """A `PlannedRun` built by hand, the way `test_stage_remote_state.py`
    does -- `execute` never re-asks a stage anything, so a test of its
    recording behaviour does not need a real `build_plan` walk."""
    stage_plans = tuple(StagePlan.work(s.name, "test work") for s in stages)
    return PlannedRun(
        plan=Plan(listing=LISTING, is_live=False, etsy_listing_id=None, stage_plans=stage_plans),
        states=tuple(
            StageState(
                stage=s,  # type: ignore[arg-type]
                desired={"stage": s.name},
                applied=None,
                live=None,
                stage_plan=sp,
            )
            for s, sp in zip(stages, stage_plans, strict=True)
        ),
    )


# --------------------------------------------------------- `execute` directly


def test_record_is_called_after_every_stage_that_succeeds(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    recorded: list[Lockfile] = []
    render = _Stage("render")
    printify_product = _Stage("printify_product", remote={"printify_product_id": "p1"})

    execute(ctx, _planned(render, printify_product), a_lock(), record=recorded.append)

    assert [lock.stages_completed for lock in recorded] == [
        ["render"],
        ["render", "printify_product"],
    ]
    assert recorded[-1].remote == {"printify_product_id": "p1"}


def test_a_raising_stage_is_recorded_marked_incomplete_then_reraised(workspace_root: Path) -> None:
    """The PRD 48 scenario: `printify_product` creates a product, then
    `etsy_listing` raises. The product id must survive the crash, and the
    lockfile must say the run did not finish."""
    ctx = a_context(workspace_root)
    recorded: list[Lockfile] = []
    printify_product = _Stage("printify_product", remote={"printify_product_id": "p1"})
    etsy_listing = _Stage("etsy_listing", fails=True)

    with pytest.raises(UserFacingError, match="etsy_listing refused"):
        execute(ctx, _planned(printify_product, etsy_listing), a_lock(), record=recorded.append)

    assert len(recorded) == 2, "one record per succeeding stage, one more for the failure"
    after_create, after_failure = recorded
    assert after_create.remote == {"printify_product_id": "p1"}
    assert after_create.incomplete is None, "nothing has failed yet at this point"
    assert after_failure.remote == {"printify_product_id": "p1"}, (
        "the create must survive the crash -- this is the whole of PRD 48's guard"
    )
    assert after_failure.incomplete == IncompleteApply(stage="etsy_listing")


def test_the_marker_names_the_stage_that_raised_not_the_last_one_that_ran(
    workspace_root: Path,
) -> None:
    ctx = a_context(workspace_root)
    recorded: list[Lockfile] = []
    render = _Stage("render")
    failing = _Stage("printify_product", fails=True)

    with pytest.raises(UserFacingError):
        execute(ctx, _planned(render, failing), a_lock(), record=recorded.append)

    assert recorded[-1].incomplete == IncompleteApply(stage="printify_product")


def test_a_fully_successful_run_clears_a_previously_set_incomplete_marker(
    workspace_root: Path,
) -> None:
    """`execute`'s own half of "a clean re-run clears it": the marker a prior
    failed run left behind must not survive a run that finishes clean."""
    ctx = a_context(workspace_root)
    lock = a_lock().marked_incomplete("etsy_listing")
    recorded: list[Lockfile] = []

    result = execute(
        ctx, _planned(_Stage("render"), _Stage("etsy_listing")), lock, record=recorded.append
    )

    assert result.incomplete is None
    assert recorded[-1].incomplete is None, "the last write on disk must also be clean"


def test_a_run_with_nothing_left_to_do_still_clears_a_stale_marker(workspace_root: Path) -> None:
    """The edge case the plain per-stage recording alone would miss: if every
    stage already matches (`will_run=False`, no `changes`), the loop never
    calls `stage.apply` at all, so there is no per-stage fold to record a
    cleared marker from. `execute` still has to notice, once, that the
    marker it started with belongs to a run that is now moot."""
    ctx = a_context(workspace_root)
    lock = a_lock().marked_incomplete("etsy_listing")
    recorded: list[Lockfile] = []
    stage_plan = StagePlan.no_work("etsy_listing")
    planned = PlannedRun(
        plan=Plan(listing=LISTING, is_live=False, etsy_listing_id=None, stage_plans=(stage_plan,)),
        states=(
            StageState(
                stage=_Stage("etsy_listing"),  # type: ignore[arg-type]
                desired={"stage": "etsy_listing"},
                applied=None,
                live=None,
                stage_plan=stage_plan,
            ),
        ),
    )

    result = execute(ctx, planned, lock, record=recorded.append)

    assert result.incomplete is None
    assert len(recorded) == 1, "no stage ran, so the only call is the explicit clear"
    assert recorded[0].incomplete is None


def test_execute_without_a_record_callback_still_runs(workspace_root: Path) -> None:
    """Every existing direct caller of `execute` passes no `record` at all --
    that has to keep working unmodified."""
    ctx = a_context(workspace_root)

    result = execute(ctx, _planned(_Stage("render")), a_lock())

    assert result.stages_completed == ["render"]


# -------------------------------------------------------- through `apply_listings`


def _lock_path(root: Path, listing: str = LISTING) -> Path:
    return root / "listings" / listing / "state.lock.json"


def test_apply_listings_writes_the_lockfile_after_the_stage_before_the_failure(
    workspace_root: Path,
) -> None:
    """The behaviour PRD 48 needs: `apply_listings` must not wait for the
    whole run to finish before anything reaches disk."""
    ctx = a_context(workspace_root)
    stages = [
        _Stage("render", remote={}),
        _Stage("printify_product", remote={"printify_product_id": "p1"}),
        _Stage("etsy_listing", fails=True),
    ]

    apply_listings(ctx, [LISTING], stages)  # type: ignore[arg-type]

    on_disk = Lockfile.read(_lock_path(workspace_root))
    assert on_disk is not None
    assert on_disk.remote == {"printify_product_id": "p1"}
    assert on_disk.stages_completed == ["render", "printify_product"]
    assert on_disk.incomplete == IncompleteApply(stage="etsy_listing")


def test_a_clean_re_run_after_a_partial_failure_clears_the_marker_on_disk(
    workspace_root: Path,
) -> None:
    """The other half of the testing table's line: "a clean re-run clears
    it". Once whatever made `etsy_listing` fail is fixed, re-running the
    same listing to completion must leave no trace of the earlier failure."""
    ctx = a_context(workspace_root)
    failing = [
        _Stage("render", remote={}),
        _Stage("printify_product", remote={"printify_product_id": "p1"}),
        _Stage("etsy_listing", fails=True),
    ]
    apply_listings(ctx, [LISTING], failing)  # type: ignore[arg-type]
    assert Lockfile.read(_lock_path(workspace_root)).incomplete is not None  # type: ignore[union-attr]

    fixed = [
        _Stage("render", remote={}),
        _Stage("printify_product", remote={"printify_product_id": "p1"}),
        _Stage("etsy_listing", remote={"etsy_listing_id": 42}),
    ]
    apply_listings(ctx, [LISTING], fixed)  # type: ignore[arg-type]

    on_disk = Lockfile.read(_lock_path(workspace_root))
    assert on_disk is not None
    assert on_disk.incomplete is None
    assert on_disk.remote == {"printify_product_id": "p1", "etsy_listing_id": 42}

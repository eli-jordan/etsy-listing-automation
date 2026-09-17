"""A33: a graceful ``should_stop`` boundary, threaded through ``execute``,
``plan_listings`` and ``apply_listings`` -- what the UI's runs executor uses
to honour a plan run's cancel and a shutdown's "finish the stage you're in,
start no other" (decision 7).

Distinct from A29's partial-apply tests (``test_partial_apply.py``): those are
about what a *failure* records; this is about what a deliberate, error-free
pause leaves behind, which is why the ``incomplete`` marker behaves
differently in each case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, StageState
from etsy_listings.engine.run import apply_listings, plan_listings
from etsy_listings.engine.stage import StageApplyResult

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, copy_listing


class _AppliedDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = True


@dataclass
class _Stage:
    name: str
    local: bool = True
    applied_model: type[_AppliedDoc] = _AppliedDoc
    remote: dict[str, Any] = field(default_factory=dict)

    def desired(self, ctx: RunContext, listing: str, applied: _AppliedDoc | None) -> dict[str, Any]:
        return {"stage": self.name}

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: _AppliedDoc | None
    ) -> None:
        return None

    def plan(self, desired: Any, applied: Any, live: Any) -> Verdict:
        return Verdict.work(f"{self.name} has work to do")

    def apply(
        self, ctx: RunContext, desired: Any, applied: Any, live: Any, lock: Lockfile
    ) -> StageApplyResult:
        return StageApplyResult(applied={"ok": True}, remote=self.remote)


def _planned(*stages: _Stage) -> PlannedRun:
    stage_plans = tuple(StagePlan(stage=s.name, will_run=True) for s in stages)
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


# --------------------------------------------------------------- `execute`


def test_should_stop_finishes_the_current_stage_and_starts_no_other(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    calls = {"count": 0}

    def stop() -> bool:
        # False on the first check (before "render"), True from then on --
        # so "render" runs and "printify_product" never starts.
        calls["count"] += 1
        return calls["count"] > 1

    result = execute(
        ctx,
        _planned(_Stage("render"), _Stage("printify_product")),
        a_lock(),
        should_stop=stop,
    )

    assert result.stages_completed == ["render"]


def test_a_graceful_stop_does_not_clear_a_previous_incomplete_marker(workspace_root: Path) -> None:
    """Unlike a clean finish, a run that never got to walk every stage cannot
    know the marker's stage is now satisfied -- clearing it here would be
    exactly the false "clean" reading A29's marker exists to prevent."""
    ctx = a_context(workspace_root)
    lock = a_lock().marked_incomplete("printify_product")

    result = execute(ctx, _planned(_Stage("render")), lock, should_stop=lambda: True)

    assert result.stages_completed == []
    assert result.incomplete is not None


def test_stopping_before_the_first_stage_records_nothing(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)

    result = execute(ctx, _planned(_Stage("render")), a_lock(), should_stop=lambda: True)

    assert result.stages_completed == []


def test_execute_without_should_stop_runs_every_stage(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)

    result = execute(ctx, _planned(_Stage("render"), _Stage("printify_product")), a_lock())

    assert result.stages_completed == ["render", "printify_product"]


# --------------------------------------------------------- `plan_listings`


def test_plan_listings_should_stop_is_checked_between_listings(workspace_root: Path) -> None:
    copy_listing(workspace_root, "second")
    ctx = a_context(workspace_root)
    seen: list[str] = []

    def stop() -> bool:
        return len(seen) >= 1

    from etsy_listings.engine.run import RunObserver

    plan_listings(
        ctx,
        [LISTING, "second"],
        [_Stage("render")],  # type: ignore[list-item]
        observer=RunObserver(on_listing_planned=lambda name, planned: seen.append(name)),
        should_stop=stop,
    )

    assert seen == [LISTING], "the second listing must never have started"


# --------------------------------------------------------- `apply_listings`


def test_apply_listings_should_stop_before_any_listing_applies_nothing(
    workspace_root: Path,
) -> None:
    ctx = a_context(workspace_root)

    report = apply_listings(ctx, [LISTING], [_Stage("render")], should_stop=lambda: True)  # type: ignore[list-item]

    assert report.outcomes == ()
    assert not (workspace_root / "listings" / LISTING / "state.lock.json").is_file()


def test_apply_listings_without_should_stop_behaves_as_before(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)

    report = apply_listings(ctx, [LISTING], [_Stage("render")])  # type: ignore[list-item]

    assert not report.failed
    assert (workspace_root / "listings" / LISTING / "state.lock.json").is_file()

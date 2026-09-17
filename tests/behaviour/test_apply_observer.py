"""A33: ``execute`` brackets each stage's own ``apply`` with
``RunObserver.on_stage_applying``/``on_stage_applied``, and fires
``on_stage_failed`` once with the exception's own message before re-raising.

These three exist to feed the UI's runs resource (``ui/runs/executor.py``):
a run needs to say *which* stage is currently applying, not just that the
listing as a whole is "applying" -- and needs to know which stage failed
without parsing the exception message. `test_partial_apply.py` covers what
``execute`` writes to the lockfile through the same raise; this file is only
about what it tells an observer.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan, Verdict
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, StageState
from etsy_listings.engine.run import RunObserver, apply_listings
from etsy_listings.engine.stage import StageApplyResult
from etsy_listings.errors import INTERNAL_ERROR_MESSAGE, UserFacingError

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock


class _AppliedDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = True


@dataclass
class _Stage:
    name: str
    local: bool = True
    applied_model: type[_AppliedDoc] = _AppliedDoc
    remote: dict[str, Any] = field(default_factory=dict)
    fails: bool = False
    defect: bool = False

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
        if self.fails:
            raise UserFacingError(f"{self.name} refused")
        if self.defect:
            raise RuntimeError(f"connection to internal-db-host refused for {self.name}")
        return StageApplyResult(applied={"ok": True}, remote=self.remote)


def _planned(*stages: _Stage, listing: str = LISTING) -> PlannedRun:
    stage_plans = tuple(StagePlan(stage=s.name, will_run=True) for s in stages)
    return PlannedRun(
        plan=Plan(listing=listing, is_live=False, etsy_listing_id=None, stage_plans=stage_plans),
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


def test_stage_applying_and_applied_fire_around_a_successful_stage(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    order: list[str] = []

    execute(
        ctx,
        _planned(_Stage("render"), _Stage("printify_product")),
        a_lock(),
        observer=RunObserver(
            on_stage_applying=lambda listing, stage: order.append(f"applying:{listing}:{stage}"),
            on_stage_applied=lambda listing, stage: order.append(f"applied:{listing}:{stage}"),
        ),
    )

    assert order == [
        f"applying:{LISTING}:render",
        f"applied:{LISTING}:render",
        f"applying:{LISTING}:printify_product",
        f"applied:{LISTING}:printify_product",
    ]


def test_stage_failed_fires_with_the_exceptions_message_before_reraising(
    workspace_root: Path,
) -> None:
    ctx = a_context(workspace_root)
    applied: list[str] = []
    failed: list[tuple[str, str]] = []

    with contextlib.suppress(UserFacingError):
        execute(
            ctx,
            _planned(_Stage("render"), _Stage("etsy_listing", fails=True)),
            a_lock(),
            observer=RunObserver(
                on_stage_applied=lambda listing, stage: applied.append(stage),
                on_stage_failed=lambda listing, stage, message: failed.append((stage, message)),
            ),
        )

    assert applied == ["render"], "the stage that failed must not also report applied"
    assert failed == [("etsy_listing", "etsy_listing refused")]


def test_a_bare_defect_reaches_on_stage_failed_masked_not_verbatim(workspace_root: Path) -> None:
    """A stage's own bug can say anything -- a connection string, a secret
    interpolated into an f-string. `on_stage_failed` feeds a client-visible
    event (the UI's runs resource), so only a `UserFacingError`'s message is
    safe to forward; anything else must be masked here, the same rule `_over`
    already applies to a listing-level failure. The exception `execute`
    re-raises still carries the real text, for the server log."""
    ctx = a_context(workspace_root)
    failed: list[tuple[str, str]] = []

    with pytest.raises(RuntimeError, match="internal-db-host") as excinfo:
        execute(
            ctx,
            _planned(_Stage("etsy_listing", defect=True)),
            a_lock(),
            observer=RunObserver(
                on_stage_failed=lambda listing, stage, message: failed.append((stage, message)),
            ),
        )

    assert failed == [("etsy_listing", INTERNAL_ERROR_MESSAGE)]
    assert "internal-db-host" not in failed[0][1]
    assert "internal-db-host" in str(excinfo.value), "the real message must still reach the log"


def test_a_stage_that_never_runs_fires_neither_callback(workspace_root: Path) -> None:
    """A ``StagePlan`` with no work and no drift is skipped by ``execute``
    entirely -- the observer must not be told a stage is "applying" one that
    was never asked to."""
    ctx = a_context(workspace_root)
    stage = _Stage("render")
    stage_plan = StagePlan(stage="render", will_run=False)
    planned = PlannedRun(
        plan=Plan(listing=LISTING, is_live=False, etsy_listing_id=None, stage_plans=(stage_plan,)),
        states=(
            StageState(
                stage=stage,  # type: ignore[arg-type]
                desired={"stage": "render"},
                applied=None,
                live=None,
                stage_plan=stage_plan,
            ),
        ),
    )
    seen: list[str] = []

    execute(
        ctx,
        planned,
        a_lock(),
        observer=RunObserver(on_stage_applying=lambda listing, stage: seen.append(stage)),
    )

    assert seen == []


def test_execute_without_an_observer_still_runs(workspace_root: Path) -> None:
    """Every existing direct caller of `execute` passes no `observer` at
    all -- that has to keep working unmodified."""
    ctx = a_context(workspace_root)

    result = execute(ctx, _planned(_Stage("render")), a_lock())

    assert result.stages_completed == ["render"]


def test_apply_listings_threads_its_own_observer_into_execute(workspace_root: Path) -> None:
    """`apply_listings` is the CLI's and the UI's entry point -- the observer
    it is handed has to reach `execute`, not just `build_plan`."""
    ctx = a_context(workspace_root)
    from etsy_listings.engine.stages.render import RenderStage

    seen: list[str] = []

    apply_listings(
        ctx,
        [LISTING],
        [RenderStage()],
        observer=RunObserver(on_stage_applying=lambda listing, stage: seen.append(stage)),
    )

    assert seen == ["render"]

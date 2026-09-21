"""A33: the engine reports one typed event stream around stage application."""

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
from etsy_listings.engine.events import (
    EngineProgress,
    EngineRunEvent,
    EngineStageApplied,
    EngineStageApplying,
    EngineStageFailed,
)
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, StageState
from etsy_listings.engine.run import apply_listings
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
    stage_plans = tuple(StagePlan.work(s.name, f"{s.name} has work to do") for s in stages)
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


def test_stage_events_and_progress_are_one_ordered_stream(workspace_root: Path) -> None:
    events: list[EngineRunEvent] = []

    execute(
        a_context(workspace_root),
        _planned(_Stage("render"), _Stage("printify_product")),
        a_lock(),
        on_event=events.append,
    )

    assert [
        (type(event), event.listing, event.stage)
        for event in events
        if isinstance(event, EngineStageApplying | EngineStageApplied)
    ] == [
        (EngineStageApplying, LISTING, "render"),
        (EngineStageApplied, LISTING, "render"),
        (EngineStageApplying, LISTING, "printify_product"),
        (EngineStageApplied, LISTING, "printify_product"),
    ]
    assert [
        (event.stage, event.message) for event in events if isinstance(event, EngineProgress)
    ] == [
        ("render", "applying render"),
        ("printify_product", "applying printify_product"),
    ]


def test_stage_failed_carries_a_safe_message_before_reraising(workspace_root: Path) -> None:
    events: list[EngineRunEvent] = []

    with contextlib.suppress(UserFacingError):
        execute(
            a_context(workspace_root),
            _planned(_Stage("render"), _Stage("etsy_listing", fails=True)),
            a_lock(),
            on_event=events.append,
        )

    assert [event.stage for event in events if isinstance(event, EngineStageApplied)] == ["render"]
    assert [
        (event.stage, event.message) for event in events if isinstance(event, EngineStageFailed)
    ] == [("etsy_listing", "etsy_listing refused")]


def test_a_bare_defect_is_masked_on_the_event_stream(workspace_root: Path) -> None:
    events: list[EngineRunEvent] = []

    with pytest.raises(RuntimeError, match="internal-db-host") as excinfo:
        execute(
            a_context(workspace_root),
            _planned(_Stage("etsy_listing", defect=True)),
            a_lock(),
            on_event=events.append,
        )

    failed = [event for event in events if isinstance(event, EngineStageFailed)]
    assert [(event.stage, event.message) for event in failed] == [
        ("etsy_listing", INTERNAL_ERROR_MESSAGE)
    ]
    assert "internal-db-host" not in failed[0].message
    assert "internal-db-host" in str(excinfo.value)


def test_a_stage_that_never_runs_emits_no_apply_event(workspace_root: Path) -> None:
    stage = _Stage("render")
    stage_plan = StagePlan.no_work("render")
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
    events: list[EngineRunEvent] = []

    execute(a_context(workspace_root), planned, a_lock(), on_event=events.append)

    assert events == []


def test_execute_without_an_event_sink_still_runs(workspace_root: Path) -> None:
    result = execute(a_context(workspace_root), _planned(_Stage("render")), a_lock())

    assert result.stages_completed == ["render"]


def test_apply_listings_threads_the_event_sink_into_execute(workspace_root: Path) -> None:
    from etsy_listings.engine.stages.render import RenderStage

    events: list[EngineRunEvent] = []
    apply_listings(
        a_context(workspace_root),
        [LISTING],
        [RenderStage()],
        on_event=events.append,
    )

    assert [event.stage for event in events if isinstance(event, EngineStageApplying)] == ["render"]

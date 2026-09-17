"""``engine.preview``: whether a planned listing still needs a preview
render, without the executor peeking at ``RenderSnapshot``."""

from __future__ import annotations

from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.plan import PlannedRun, StageState
from etsy_listings.engine.preview import needs_preview
from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.render import (
    RenderSceneSnapshot,
    RenderSceneState,
    RenderSnapshot,
    RenderStage,
)


def _plan(*, snapshot: RenderSnapshot | None, desired: object | None = None) -> PlannedRun:
    stage = RenderStage()
    return PlannedRun(
        plan=Plan(listing="take-a-hike", is_live=False, etsy_listing_id=None, stage_plans=()),
        states=(
            StageState(
                stage=stage,
                desired=object() if desired is None else desired,
                applied=None,
                live=None,
                stage_plan=StagePlan(stage="render", will_run=False, snapshot=snapshot),
            ),
        ),
    )


def _scene(*, state: RenderSceneState, preview: bool) -> RenderSceneSnapshot:
    return RenderSceneSnapshot(
        scene="flat-lay-01/black",
        template="flat-lay-01",
        colour="black",
        state=state,
        preview=preview,
    )


def test_stale_without_a_preview_needs_one() -> None:
    assert needs_preview(
        _plan(snapshot=RenderSnapshot(scenes=(_scene(state="stale", preview=False),)))
    )


def test_missing_without_a_preview_needs_one() -> None:
    assert needs_preview(
        _plan(snapshot=RenderSnapshot(scenes=(_scene(state="missing", preview=False),)))
    )


def test_stale_that_already_has_a_preview_does_not() -> None:
    assert not needs_preview(
        _plan(snapshot=RenderSnapshot(scenes=(_scene(state="stale", preview=True),)))
    )


def test_cached_does_not_need_a_preview() -> None:
    assert not needs_preview(
        _plan(snapshot=RenderSnapshot(scenes=(_scene(state="cached", preview=False),)))
    )


def test_a_blocked_render_stage_does_not() -> None:
    assert not needs_preview(
        _plan(
            snapshot=RenderSnapshot(scenes=(_scene(state="missing", preview=False),)),
            desired=Blocked("no garment profile"),
        )
    )


def test_a_plan_with_no_render_stage_does_not() -> None:
    planned = PlannedRun(
        plan=Plan(listing="take-a-hike", is_live=False, etsy_listing_id=None, stage_plans=()),
        states=(),
    )
    assert not needs_preview(planned)


def test_a_non_render_snapshot_does_not() -> None:
    assert not needs_preview(_plan(snapshot=None))

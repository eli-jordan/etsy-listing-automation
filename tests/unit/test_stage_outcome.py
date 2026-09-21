"""The stage decision interface: exactly one legal outcome (A33)."""

from __future__ import annotations

from etsy_listings.engine.change import (
    FieldChange,
    StageBlocked,
    StageIdle,
    StagePlan,
    StageWork,
    Verdict,
)


def test_stage_plan_derives_every_legacy_view_from_one_outcome() -> None:
    change = FieldChange(path="title", before="Old", after="New")

    idle = StagePlan(stage="render", outcome=StageIdle())
    work = StagePlan(
        stage="etsy_listing",
        outcome=StageWork(reason="the title changed", changes=(change,)),
    )
    blocked = StagePlan(
        stage="publish",
        outcome=StageBlocked(message="the price is below cost"),
    )

    assert (idle.will_run, idle.reason, idle.blocked, idle.changes) == (
        False,
        None,
        None,
        (),
    )
    assert (work.will_run, work.reason, work.blocked, work.changes) == (
        True,
        "the title changed",
        None,
        (change,),
    )
    assert (blocked.will_run, blocked.reason, blocked.blocked, blocked.changes) == (
        False,
        None,
        "the price is below cost",
        (),
    )


def test_verdict_factories_construct_the_same_closed_outcomes() -> None:
    idle = Verdict.no_work()
    work = Verdict.work("the listing changed")
    refused = Verdict.refused("the price is below cost")

    assert isinstance(idle.outcome, StageIdle)
    assert isinstance(work.outcome, StageWork)
    assert isinstance(refused.outcome, StageBlocked)

"""``ui/runs/events.py``: DTO conversion for the SSE stream (A33, decision 7).

Pure, like ``plan_fingerprint`` -- no registry, no executor, no workspace.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from etsy_listings.config.money import Money
from etsy_listings.engine.change import (
    Action,
    Drift,
    FieldChange,
    ListChange,
    MediaChange,
    Plan,
    PriceChange,
    StagePlan,
)
from etsy_listings.engine.stages.publish import PublishSnapshot
from etsy_listings.ui.runs.events import (
    BlockedOutcomeDTO,
    IdleOutcomeDTO,
    ListingFailedEvent,
    ListingPlannedEvent,
    PhaseEvent,
    ProgressEvent,
    RenderStagePlanDTO,
    RunEvent,
    StageOutcomeDTO,
    WorkOutcomeDTO,
    plan_dto,
    stage_plan_dto,
)


class _WrongSnapshot(BaseModel):
    note: str
    price: Money


def test_field_change_round_trips_through_the_dto() -> None:
    sp = StagePlan.work(
        "etsy_listing",
        "copy changed",
        changes=(FieldChange(path="title", before="Old", after="New"),),
    )

    dto = stage_plan_dto(sp)
    assert isinstance(dto.outcome, WorkOutcomeDTO)

    assert dto.outcome.changes[0].kind == "field"
    assert dto.outcome.changes[0].model_dump() == {
        "kind": "field",
        "path": "title",
        "before": "Old",
        "after": "New",
    }


def test_price_change_renders_money_as_its_display_string() -> None:
    sp = StagePlan.work(
        "publish",
        "price changed",
        changes=(
            PriceChange(
                size="M",
                color="black",
                before=Money(Decimal("349"), "NOK"),
                after=Money(Decimal("399"), "NOK"),
            ),
        ),
    )

    dto = stage_plan_dto(sp)
    assert isinstance(dto.outcome, WorkOutcomeDTO)

    assert dto.outcome.changes[0].kind == "price"
    assert dto.outcome.changes[0].before == "349 NOK"
    assert dto.outcome.changes[0].after == "399 NOK"


def test_list_change_and_media_change_keep_their_own_kind() -> None:
    sp = StagePlan.work(
        "printify_product",
        "product changed",
        changes=(
            ListChange(path="colors", added=("navy",), removed=()),
            MediaChange(rank=0, before="old.png", after="new.png"),
        ),
    )

    dto = stage_plan_dto(sp)
    assert isinstance(dto.outcome, WorkOutcomeDTO)

    assert [c.kind for c in dto.outcome.changes] == ["list", "media"]


def test_drift_carries_its_labels() -> None:
    sp = StagePlan.no_work(
        "etsy_listing",
        drift=(
            Drift(
                path="shipping_profile_id",
                last_applied=1,
                live=2,
                last_applied_label="A",
                live_label="B",
            ),
        ),
    )

    dto = stage_plan_dto(sp)

    assert dto.drift[0].last_applied_label == "A"
    assert dto.drift[0].live_label == "B"


def test_actions_carry_their_paths() -> None:
    sp = StagePlan.work(
        "render",
        "scene changed",
        actions=(Action(description="render scene", inputs=("a.png",), outputs=("b.png",)),),
    )

    dto = stage_plan_dto(sp)
    assert isinstance(dto.outcome, WorkOutcomeDTO)

    assert dto.outcome.actions[0].description == "render scene"
    assert dto.outcome.actions[0].inputs == ("a.png",)


def test_snapshot_keeps_the_model_declared_by_its_stage() -> None:
    sp = StagePlan.no_work("publish", snapshot=PublishSnapshot())

    dto = stage_plan_dto(sp)

    assert isinstance(dto.snapshot, PublishSnapshot)


def test_a_snapshot_from_the_wrong_stage_is_rejected() -> None:
    sp = StagePlan.no_work(
        "publish", snapshot=_WrongSnapshot(note="no", price=Money(Decimal("10"), "NOK"))
    )

    with pytest.raises(TypeError, match="PublishSnapshot"):
        stage_plan_dto(sp)


def test_a_stage_plan_with_no_snapshot_carries_none() -> None:
    dto = stage_plan_dto(StagePlan.no_work("render"))

    assert dto.snapshot is None


def test_plan_dto_carries_every_stage_plan_in_order() -> None:
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(
            StagePlan.work("render", "scene changed"),
            StagePlan.block("printify_product", "no shop configured"),
        ),
    )

    dto = plan_dto(plan)

    assert [sp.stage for sp in dto.stage_plans] == ["render", "printify_product"]
    assert dto.stage_plans[1].outcome == BlockedOutcomeDTO(message="no shop configured")


def test_stage_outcome_dto_accepts_only_complete_closed_variants() -> None:
    adapter = TypeAdapter(StageOutcomeDTO)

    assert adapter.validate_python({"type": "idle"}) == IdleOutcomeDTO()
    assert adapter.validate_python({"type": "work", "reason": "changed"}) == WorkOutcomeDTO(
        reason="changed"
    )
    assert adapter.validate_python(
        {"type": "blocked", "message": "missing shop"}
    ) == BlockedOutcomeDTO(message="missing shop")

    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "work"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "blocked"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "idle", "reason": "contradiction"})


def test_stage_plan_rejects_work_fields_outside_the_work_outcome() -> None:
    with pytest.raises(ValidationError):
        RenderStagePlanDTO.model_validate(
            {
                "stage": "render",
                "outcome": {"type": "idle"},
                "changes": [{"kind": "field", "path": "title", "before": "old", "after": "new"}],
            }
        )


def test_run_event_union_discriminates_on_type() -> None:
    """`RunDetail.events` decodes a heterogeneous list by `type` alone -- this
    is what makes the field usable in a pydantic model at all, and what
    `gen:api` turns into a discriminated TypeScript union."""
    adapter = TypeAdapter(list[RunEvent])

    events = adapter.validate_python(
        [
            {"type": "phase", "id": 1, "phase": "queued"},
            {
                "type": "progress",
                "id": 2,
                "listing": "take-a-hike",
                "stage": "render",
                "message": "hi",
            },
        ]
    )

    assert isinstance(events[0], PhaseEvent)
    assert isinstance(events[1], ProgressEvent)


def test_listing_planned_event_carries_the_plan_and_fingerprint() -> None:
    plan = Plan(listing="take-a-hike", is_live=False, etsy_listing_id=None, stage_plans=())

    event = ListingPlannedEvent(
        id=1, listing="take-a-hike", plan=plan_dto(plan), fingerprint="sha256:abc"
    )

    assert event.fingerprint == "sha256:abc"
    assert event.plan.listing == "take-a-hike"


def test_listing_failed_event_stale_plan_defaults_to_none() -> None:
    event = ListingFailedEvent(id=1, listing="take-a-hike", message="boom")

    assert event.stale_plan is None

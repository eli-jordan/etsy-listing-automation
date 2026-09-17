"""``ui/runs/events.py``: DTO conversion for the SSE stream (A33, decision 7).

Pure, like ``plan_fingerprint`` -- no registry, no executor, no workspace.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, TypeAdapter

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
from etsy_listings.ui.runs.events import (
    ListingFailedEvent,
    ListingPlannedEvent,
    PhaseEvent,
    ProgressEvent,
    RunEvent,
    plan_dto,
    stage_plan_dto,
)


class _Snapshot(BaseModel):
    note: str
    price: Money


def test_field_change_round_trips_through_the_dto() -> None:
    sp = StagePlan(
        stage="etsy_listing",
        will_run=True,
        changes=(FieldChange(path="title", before="Old", after="New"),),
    )

    dto = stage_plan_dto(sp)

    assert dto.changes[0].kind == "field"
    assert dto.changes[0].model_dump() == {
        "kind": "field",
        "path": "title",
        "before": "Old",
        "after": "New",
    }


def test_price_change_renders_money_as_its_display_string() -> None:
    sp = StagePlan(
        stage="publish",
        will_run=True,
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

    assert dto.changes[0].kind == "price"
    assert dto.changes[0].before == "349 NOK"
    assert dto.changes[0].after == "399 NOK"


def test_list_change_and_media_change_keep_their_own_kind() -> None:
    sp = StagePlan(
        stage="printify_product",
        will_run=True,
        changes=(
            ListChange(path="colors", added=("navy",), removed=()),
            MediaChange(rank=0, before="old.png", after="new.png"),
        ),
    )

    dto = stage_plan_dto(sp)

    assert [c.kind for c in dto.changes] == ["list", "media"]


def test_drift_carries_its_labels() -> None:
    sp = StagePlan(
        stage="etsy_listing",
        will_run=False,
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
    sp = StagePlan(
        stage="render",
        will_run=True,
        actions=(Action(description="render scene", inputs=("a.png",), outputs=("b.png",)),),
    )

    dto = stage_plan_dto(sp)

    assert dto.actions[0].description == "render scene"
    assert dto.actions[0].inputs == ("a.png",)


def test_snapshot_is_dumped_generically_and_keeps_a_money_field() -> None:
    sp = StagePlan(
        stage="publish",
        will_run=False,
        snapshot=_Snapshot(note="ok", price=Money(Decimal("10"), "NOK")),
    )

    dto = stage_plan_dto(sp)

    assert dto.snapshot == {"note": "ok", "price": "10 NOK"}


def test_a_stage_plan_with_no_snapshot_carries_none() -> None:
    dto = stage_plan_dto(StagePlan(stage="render", will_run=False))

    assert dto.snapshot is None


def test_plan_dto_carries_every_stage_plan_in_order() -> None:
    plan = Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(
            StagePlan(stage="render", will_run=True),
            StagePlan(stage="printify_product", will_run=False, blocked="no shop configured"),
        ),
    )

    dto = plan_dto(plan)

    assert [sp.stage for sp in dto.stage_plans] == ["render", "printify_product"]
    assert dto.stage_plans[1].blocked == "no shop configured"


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

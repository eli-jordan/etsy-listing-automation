"""``plan_fingerprint`` (A31): the digest ``apply`` compares against ``expect``
before running a single stage.

Pure and unit-testable without a workspace, a lockfile or a fake client --
``plan_fingerprint`` takes only a :class:`~etsy_listings.engine.change.Plan`.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from etsy_listings.config.money import Money
from etsy_listings.engine.change import (
    Action,
    Drift,
    FieldChange,
    ListChange,
    Plan,
    PriceChange,
    StagePlan,
)
from etsy_listings.engine.run import plan_fingerprint


class _Snapshot(BaseModel):
    note: str


def _plan(**stage_plan_overrides: object) -> Plan:
    fields: dict[str, object] = {
        "stage": "printify_product",
        "will_run": True,
        "reason": "no Printify product yet -- it will be created",
        "changes": (
            FieldChange(path="title", before="Old", after="New"),
            PriceChange(
                size="M",
                color="black",
                before=Money(Decimal("349"), "NOK"),
                after=Money(Decimal("399"), "NOK"),
            ),
            ListChange(path="colors", added=("navy",), removed=()),
        ),
        "drift": (Drift(path="visible", last_applied=False, live=True),),
        "actions": (Action(description="create a Printify product", inputs=("d.png",)),),
    }
    fields.update(stage_plan_overrides)
    return Plan(
        listing="take-a-hike",
        is_live=False,
        etsy_listing_id=None,
        stage_plans=(StagePlan(**fields),),  # type: ignore[arg-type]
    )


def test_the_same_plan_fingerprints_the_same() -> None:
    assert plan_fingerprint(_plan()) == plan_fingerprint(_plan())


def test_a_snapshot_difference_alone_does_not_change_the_fingerprint() -> None:
    """Snapshots are excluded (A31): they carry things that can change
    between two otherwise-identical plans, like an Etsy CDN URL, and hashing
    one would make `apply` refuse a plan nobody actually disagreed with."""
    with_one_snapshot = _plan(snapshot=_Snapshot(note="first read"))
    with_a_different_snapshot = _plan(snapshot=_Snapshot(note="second read, moments later"))

    assert plan_fingerprint(with_one_snapshot) == plan_fingerprint(with_a_different_snapshot)


def test_no_snapshot_and_a_snapshot_also_fingerprint_the_same() -> None:
    assert plan_fingerprint(_plan(snapshot=None)) == plan_fingerprint(
        _plan(snapshot=_Snapshot(note="anything"))
    )


def test_a_real_change_changes_the_fingerprint() -> None:
    baseline = _plan()
    changed = _plan(changes=(FieldChange(path="title", before="Old", after="Something Else"),))

    assert plan_fingerprint(baseline) != plan_fingerprint(changed)


def test_drift_changes_the_fingerprint() -> None:
    """Deliberate (A31): if Etsy drifted between review and apply, applying
    a cached plan would revert something the user never saw reverted."""
    baseline = _plan()
    drifted = _plan(drift=())

    assert plan_fingerprint(baseline) != plan_fingerprint(drifted)


def test_actions_change_the_fingerprint() -> None:
    baseline = _plan()
    different_actions = _plan(actions=())

    assert plan_fingerprint(baseline) != plan_fingerprint(different_actions)


def test_a_different_listing_name_changes_the_fingerprint() -> None:
    one = _plan()
    other = Plan(
        listing="another-listing",
        is_live=one.is_live,
        etsy_listing_id=one.etsy_listing_id,
        stage_plans=one.stage_plans,
    )

    assert plan_fingerprint(one) != plan_fingerprint(other)


def test_money_renders_as_the_string_a_listing_would_recognise() -> None:
    """A `Decimal` amount is not JSON-serialisable; `canonical_hash` would
    raise before this PR's `_canonical` learned to render `Money` as its
    string form."""
    plan = plan_fingerprint(_plan())

    assert isinstance(plan, str) and plan.startswith("sha256:")

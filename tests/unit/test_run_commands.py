"""The four legal run requests carry exactly the data their executor needs."""

from __future__ import annotations

import pytest

from etsy_listings.ui.runs.registry import (
    ListingApply,
    ListingPlan,
    Run,
    WorkspaceApply,
    WorkspacePlan,
)


@pytest.mark.parametrize(
    ("command", "kind", "scope", "listings"),
    [
        (ListingPlan(("one",)), "plan", "listings", ("one",)),
        (WorkspacePlan(("one", "two")), "plan", "workspace", ("one", "two")),
        (ListingApply(("one",), {"one": "hash"}), "apply", "listings", ("one",)),
        (
            WorkspaceApply(("one",), {"one": "hash"}, "review-run"),
            "apply",
            "workspace",
            ("one",),
        ),
    ],
)
def test_run_identity_is_derived_from_its_command(
    command: ListingPlan | WorkspacePlan | ListingApply | WorkspaceApply,
    kind: str,
    scope: str,
    listings: tuple[str, ...],
) -> None:
    run = Run(id="run-1", command=command)

    assert run.kind == kind
    assert run.scope == scope
    assert run.listings == listings


def test_plan_and_apply_have_separate_phase_transitions() -> None:
    plan = Run(id="plan", command=ListingPlan(("one",)))
    apply = Run(id="apply", command=ListingApply(("one",), {"one": "hash"}))

    plan.transition_plan("planning")
    apply.transition_apply("applying")

    assert plan.phase == "planning"
    assert apply.phase == "applying"
    with pytest.raises(TypeError):
        plan.transition_apply("applying")
    with pytest.raises(TypeError):
        apply.transition_plan("planning")

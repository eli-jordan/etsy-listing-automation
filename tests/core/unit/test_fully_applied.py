"""ADR-0050's *full success* predicate, case by case.

``fully_applied`` is pure over a :class:`ListingOutcome` and the lockfile the
apply left, so each of its guards is checked with a hand-built outcome rather
than a deployment: one row per way to fall short of full success, plus the one
row that is. Removing any guard flips exactly its row.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from etsy_listings.core.engine.change import Plan, StagePlan
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.plan import PlannedRun
from etsy_listings.core.engine.run import ListingOutcome, fully_applied
from etsy_listings.core.errors import UserFacingError

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_lock


def _planned(*stage_plans: StagePlan) -> PlannedRun:
    plan = Plan(listing=LISTING, is_live=True, etsy_listing_id=1, stage_plans=stage_plans)
    return PlannedRun(plan=plan, states=())


_RAN = StagePlan.work("render", "design changed")
_IDLE = StagePlan.no_work("etsy_listing")
_BLOCKED = StagePlan.block("etsy_listing", "no Etsy shop configured")


@dataclass(frozen=True)
class Case:
    outcome: ListingOutcome
    lock: Lockfile
    fully_applied: bool


CASES = {
    "error": Case(
        ListingOutcome(LISTING, planned=_planned(_RAN), error=UserFacingError("Etsy is down")),
        a_lock(),
        fully_applied=False,
    ),
    "absent plan": Case(ListingOutcome(LISTING), a_lock(), fully_applied=False),
    "blocked stage": Case(
        ListingOutcome(LISTING, planned=_planned(_RAN, _BLOCKED)), a_lock(), fully_applied=False
    ),
    "incomplete marker": Case(
        ListingOutcome(LISTING, planned=_planned(_RAN, _IDLE)),
        a_lock().marked_incomplete("etsy_listing"),
        fully_applied=False,
    ),
    "full success": Case(
        ListingOutcome(LISTING, planned=_planned(_RAN, _IDLE)), a_lock(), fully_applied=True
    ),
}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_fully_applied(case: Case) -> None:
    assert fully_applied(case.outcome, case.lock) is case.fully_applied

from __future__ import annotations

from etsy_listings.core.application.deploy.events import ListingPlannedEvent
from etsy_listings.core.application.deploy.registry import BatchApply, ReviewedApply, Run
from etsy_listings.core.application.refusals import ReviewedPlanRefusedError


def check_reviewed_apply(reviewed: Run | None, command: ReviewedApply) -> None:
    scope = "batch" if isinstance(command, BatchApply) else "workspace"
    batch_id = command.batch_id if isinstance(command, BatchApply) else None
    if (
        reviewed is None
        or reviewed.scope != scope
        or reviewed.kind != "plan"
        or reviewed.batch_id != batch_id
    ):
        raise ReviewedPlanRefusedError(f"reviewed_run_id is not a {scope} plan")
    if reviewed.phase != "ready":
        raise ReviewedPlanRefusedError(f"reviewed {scope} plan is not ready")
    _check_same_listings(reviewed, command, scope)


def _check_same_listings(reviewed: Run, command: ReviewedApply, scope: str) -> None:
    """The listings and fingerprints the review showed, each listing at its
    latest plan, in first-planned order."""
    fingerprints: dict[str, str] = {}
    for event in reviewed.events:
        if isinstance(event, ListingPlannedEvent):
            fingerprints[event.listing] = event.fingerprint
    if list(command.listings) != list(fingerprints):
        raise ReviewedPlanRefusedError(
            f"apply listings must exactly match the reviewed {scope} plan"
        )
    if dict(command.expect) != fingerprints:
        raise ReviewedPlanRefusedError(
            f"apply fingerprints must exactly match the reviewed {scope} plan"
        )

"""Whether a workspace or batch apply is the one the seller reviewed
(ADR-0042, ADR-0059).

A workspace apply carries no listings of its own choosing: it names the
ready workspace plan it was reviewed from and must repeat that plan's
listings, in its order, and each listing's plan fingerprint. Anything else --
a listing created or removed since, a fingerprint the review never showed --
is refused before it is queued, so a reviewed set is applied exactly or not
at all. The engine still re-plans each listing and refuses a stale
fingerprint when the apply runs (ADR-0039); this check is about the
*review*, that one is about the *workspace*.

A batch apply is held to the same rule against a ready plan of the same
listing batch.
"""

from __future__ import annotations

from etsy_listings.core.application.deploy.events import ListingPlannedEvent
from etsy_listings.core.application.deploy.registry import BatchApply, ReviewedApply, Run
from etsy_listings.core.application.refusals import ReviewedPlanRefusedError


def check_reviewed_apply(reviewed: Run | None, command: ReviewedApply) -> None:
    """Raise :class:`ReviewedPlanRefusedError` unless ``command`` names exactly
    what ``reviewed`` -- the run its ``reviewed_run_id`` names, if any --
    planned."""
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

    # A listing planned again after its previews rendered has a second event;
    # the later one is what the seller reviewed, in first-planned order.
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

"""Whether a workspace apply is the one the seller reviewed (ADR-0042).

A workspace apply carries no listings of its own choosing: it names the
ready workspace plan it was reviewed from and must repeat that plan's
listings, in its order, and each listing's plan fingerprint. Anything else --
a listing created or removed since, a fingerprint the review never showed --
is refused before it is queued, so a reviewed set is applied exactly or not
at all. The engine still re-plans each listing and refuses a stale
fingerprint when the apply runs (ADR-0039); this check is about the
*review*, that one is about the *workspace*.
"""

from __future__ import annotations

from etsy_listings.core.application.deploy.events import ListingPlannedEvent
from etsy_listings.core.application.deploy.registry import Run, WorkspaceApply
from etsy_listings.core.application.refusals import ReviewedPlanRefused


def check_reviewed_apply(reviewed: Run | None, command: WorkspaceApply) -> None:
    """Raise :class:`ReviewedPlanRefused` unless ``command`` names exactly
    what ``reviewed`` -- the run its ``reviewed_run_id`` names, if any --
    planned."""
    if reviewed is None or reviewed.scope != "workspace" or reviewed.kind != "plan":
        raise ReviewedPlanRefused("reviewed_run_id is not a workspace plan")
    if reviewed.phase != "ready":
        raise ReviewedPlanRefused("reviewed workspace plan is not ready")

    # A listing planned again after its previews rendered has a second event;
    # the later one is what the seller reviewed, in first-planned order.
    fingerprints: dict[str, str] = {}
    for event in reviewed.events:
        if isinstance(event, ListingPlannedEvent):
            fingerprints[event.listing] = event.fingerprint
    if list(command.listings) != list(fingerprints):
        raise ReviewedPlanRefused("apply listings must exactly match the reviewed workspace plan")
    if dict(command.expect) != fingerprints:
        raise ReviewedPlanRefused(
            "apply fingerprints must exactly match the reviewed workspace plan"
        )

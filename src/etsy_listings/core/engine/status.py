from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stages.etsy_listing import AppliedEtsyListing
from etsy_listings.core.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.core.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.core.workspace import Workspace

ListingLifecycle = Literal["retired", "deleted", "renew"]
ListingStatus = Literal[
    "draft",
    "deployed",
    "live",
    "dirty",
    "pending-delete",
    "pending-retire",
    "inactive",
    "expired",
]
ListingGesture = Literal["delete", "retire", "un-retire", "cancel", "renew"]


def remote_ids(workspace: Workspace, name: str) -> tuple[int | None, str | None]:
    lock = Lockfile.read(workspace.lock_file(name))
    if lock is None:
        return None, None
    etsy = lock.remote.get(ETSY_LISTING_ID_KEY)
    product = lock.remote.get(PRODUCT_ID_KEY)
    return (int(etsy) if etsy else None), (str(product) if product else None)


def workspace_listing_status(
    workspace: Workspace,
    name: str,
    *,
    live: bool,
    lifecycle: ListingLifecycle | None = None,
    etsy_state: str | None = None,
) -> ListingStatus:
    lock = Lockfile.read(workspace.lock_file(name))
    applied = lock.parse_applied_for("etsy_listing", AppliedEtsyListing) if lock else None
    return listing_status(
        StatusInputs(
            applied=lock is not None and bool(lock.stages_completed),
            edited=edited_since_apply(workspace.listing_file(name), workspace.lock_file(name)),
            live=live,
            lifecycle=lifecycle,
            etsy_state=etsy_state,
            last_applied_lifecycle="retired" if applied and applied.state == "inactive" else None,
            incomplete=lock is not None and lock.incomplete is not None,
        )
    )


def has_undeployed_changes(workspace: Workspace, name: str) -> bool:
    lock = Lockfile.read(workspace.lock_file(name))
    if lock is None or not lock.stages_completed or lock.incomplete is not None:
        return True
    return edited_since_apply(workspace.listing_file(name), workspace.lock_file(name))


LIVE_ETSY_STATES = frozenset({"active", "inactive", "sold_out", "expired", "removed"})
"""Etsy ``state`` values that mean the listing left draft at some point.

Everything except ``draft`` counts. ``inactive``/``expired``/``sold_out`` are
all *published* listings in a particular condition, and collapsing them into
"not live" would make a sold-out listing look like it had never been published
-- an edit to one is still an edit to something buyers have seen, which is
what `dirty` is for.
"""


def is_live_etsy_state(state: str | None) -> bool:
    """Whether Etsy's ``state`` means this listing has been published.

    ``None`` -- no id on record, or a state we could not read -- is **not**
    live. A listing this tool cannot prove is published is reported as though
    it were not, which is the reading that never overstates what has happened
    to a shop.
    """
    return state is not None and state in LIVE_ETSY_STATES


def edited_since_apply(listing_file: Path, lock_file: Path) -> bool:
    if not lock_file.is_file() or not listing_file.is_file():
        return False
    return listing_file.stat().st_mtime > lock_file.stat().st_mtime


@dataclass(frozen=True)
class StatusInputs:
    """The facts a listing's badge is decided from (:func:`listing_status`).

    ``lifecycle`` / ``etsy_state`` / ``last_applied_lifecycle`` are optional
    so the original four-state table still answers from the two facts it
    always had. When they *are* passed, delete/retire win over
    ``live``/``dirty``: calling a paused listing ``live`` would lie.

    ``incomplete`` is ADR-0037's marker -- a stage raised mid-``apply`` and left
    the lockfile recording only what ran before it. A per-stage write makes
    ``state.lock.json`` newer than ``listing.yaml`` partway through that
    failed run, so ``edited`` alone would read the listing as clean. The
    marker is folded into the same branch ``edited`` already decides: it
    invents no status of its own, and delete/retire still win over both.
    """

    applied: bool
    edited: bool
    live: bool
    lifecycle: ListingLifecycle | None = None
    etsy_state: str | None = None
    last_applied_lifecycle: ListingLifecycle | None = None
    incomplete: bool = False


def listing_status(inputs: StatusInputs) -> ListingStatus:
    return (
        _lifecycle_status(inputs) or _etsy_state_status(inputs.etsy_state) or _deploy_status(inputs)
    )


def _lifecycle_status(inputs: StatusInputs) -> ListingStatus | None:
    lifecycle = inputs.lifecycle
    if lifecycle == "deleted":
        return "pending-delete"
    if lifecycle == "renew" or (lifecycle is None and inputs.last_applied_lifecycle == "retired"):
        # Un-retire and pending renew: the workspace wants it on sale, Etsy
        # does not. Etsy cannot go back to `draft` (birth-only), so the
        # badge is ours.
        return "draft"
    if lifecycle == "retired":
        return "pending-retire" if inputs.etsy_state == "active" else "inactive"
    return None


def _etsy_state_status(etsy_state: str | None) -> ListingStatus | None:
    if etsy_state == "expired":
        return "expired"
    if etsy_state in {"inactive", "removed"}:
        return "inactive"
    return None


def _deploy_status(inputs: StatusInputs) -> ListingStatus:
    dirty = inputs.edited or inputs.incomplete
    if inputs.live:
        return "dirty" if dirty else "live"
    if not inputs.applied or dirty:
        return "draft"
    return "deployed"


def listing_gestures(
    *,
    lifecycle: ListingLifecycle | None = None,
    etsy_state: str | None = None,
    published: bool = False,
) -> tuple[ListingGesture, ...]:
    if lifecycle == "deleted":
        return ("cancel",)
    if lifecycle == "retired":
        return ("un-retire",)
    if not published:
        return ("delete",)
    if etsy_state in {"inactive", "expired", "removed"}:
        return ("retire", "renew")
    return ("retire",)

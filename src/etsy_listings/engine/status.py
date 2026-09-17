"""Where a listing has got to: the states the UI badges it with.

Two independent facts decide the original four, and neither is a state in
its own right:

* **has it been applied, and has it been edited since?** -- local, and the
  lockfile's question, since the lockfile *is* the record of the last apply.
* **is it live on Etsy?** -- remote, and nothing this tool ever does: PRD
  non-goal 1 says the pipeline never activates a listing it creates, so
  "live" only ever arrives because a human pressed publish in Shop Manager.

Crossing them gives the transitions the product asks for::

    draft --(apply)--> deployed --(publish on Etsy)--> live
    draft --(apply)--> deployed --(edit)--> draft --(apply)--> deployed
    live  --(edit)--> dirty --(apply)--> live

The asymmetry between ``draft`` and ``dirty`` is the point worth stating: an
edit to something that was never live takes it back to ``draft``, because
nobody is looking at the stale version -- whereas an edit to a live listing is
``dirty``, because a buyer *is*, and the gap between what Etsy shows and what
the workspace says is the thing worth a different colour.

PRD 61–67 add delete/retire on top of those four, from two more facts:
``listing.yaml``'s optional ``lifecycle:`` key, and Etsy's actual ``state``
(not the collapsed live-or-not). Those win when both could apply: a retired
listing is ``inactive``, not ``dirty``, even if the yaml was edited.

This module lives in ``engine`` for the reason the "only ``engine`` computes a
diff" invariant gives: it is the shop-side lifecycle rule, and the CLI's
`status` command (Phase 6) has to answer it the same way the UI's badge does.
The table's buttons are the same facts, as :func:`listing_gestures`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

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
    """Whether the listing document was written after the last apply.

    Modification times, not a diff, and deliberately: the question the product
    asks is "has it been *edited* since the last apply", and a write is what
    an edit is. The cost is that an edit reverted before the next apply still
    reads as an edit until one runs; the alternative is re-deriving every
    stage's desired document -- half of which (`etsy_media`'s image ids) is
    not knowable without the network -- to paint a badge.

    A missing lockfile answers ``False`` rather than ``True``: it means the
    listing has never been applied, which :func:`listing_status` reads on its
    own and would otherwise be told twice.
    """
    if not lock_file.is_file() or not listing_file.is_file():
        return False
    return listing_file.stat().st_mtime > lock_file.stat().st_mtime


def listing_status(
    *,
    applied: bool,
    edited: bool,
    live: bool,
    lifecycle: ListingLifecycle | None = None,
    etsy_state: str | None = None,
    last_applied_lifecycle: ListingLifecycle | None = None,
    incomplete: bool = False,
) -> ListingStatus:
    """The badge. Pure -- see the module docstring for what each combination
    means and why.

    ``lifecycle`` / ``etsy_state`` / ``last_applied_lifecycle`` are optional
    so the original four-state table still answers from the two facts it
    always had. When they *are* passed, delete/retire (PRD 61–67) win over
    ``live``/``dirty``: calling a paused listing ``live`` would lie.

    ``incomplete`` is A29's marker -- a stage raised mid-``apply`` and left
    the lockfile recording only what ran before it. A per-stage write makes
    ``state.lock.json`` newer than ``listing.yaml`` partway through that
    failed run, so ``edited`` alone would read the listing as clean. The
    marker is folded into the same branch ``edited`` already decides: it
    invents no status of its own, and delete/retire still win over both.
    """
    if lifecycle == "deleted":
        return "pending-delete"
    if lifecycle == "renew" or (lifecycle is None and last_applied_lifecycle == "retired"):
        # Un-retire and pending renew: the workspace wants it on sale, Etsy
        # does not. Etsy cannot go back to `draft` (birth-only), so the
        # badge is ours.
        return "draft"
    if lifecycle == "retired":
        if etsy_state == "active":
            return "pending-retire"
        return "inactive"
    if etsy_state == "expired":
        return "expired"
    if etsy_state in {"inactive", "removed"}:
        return "inactive"
    dirty = edited or incomplete
    if live:
        return "dirty" if dirty else "live"
    if not applied or dirty:
        return "draft"
    return "deployed"


def listing_gestures(
    *,
    lifecycle: ListingLifecycle | None = None,
    etsy_state: str | None = None,
    published: bool = False,
) -> tuple[ListingGesture, ...]:
    """Which buttons the listings table offers for this row (PRD 66).

    ``published`` is :func:`is_live_etsy_state`: the listing has left
    ``draft``. The original four badges do not decide the buttons -- a
    ``dirty`` live listing still retires; a never-live ``draft`` still
    deletes.
    """
    if lifecycle == "deleted":
        return ("cancel",)
    if lifecycle == "retired":
        return ("un-retire",)
    if not published:
        return ("delete",)
    if etsy_state in {"inactive", "expired", "removed"}:
        return ("retire", "renew")
    return ("retire",)

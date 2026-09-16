"""Where a listing has got to: the four states the UI badges it with.

Two independent facts decide it, and neither is a state in its own right:

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

This module lives in ``engine`` for the reason the "only ``engine`` computes a
diff" invariant gives: it is the shop-side lifecycle rule, and the CLI's
`status` command (Phase 6) has to answer it the same way the UI's badge does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

ListingStatus = Literal["draft", "deployed", "live", "dirty"]

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


def listing_status(*, applied: bool, edited: bool, live: bool) -> ListingStatus:
    """The badge, from the two facts above. Pure -- see the module docstring
    for what each combination means and why."""
    if live:
        return "dirty" if edited else "live"
    if not applied or edited:
        return "draft"
    return "deployed"

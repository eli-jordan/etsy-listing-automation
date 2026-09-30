"""Where a batch stands, worked out from its rows (UI doc §2, *Recent
batches*; spec *Review workflow*; batch plan PR 5). Pure: nothing here reads
the disk, so the index, the summary and the tests ask the same question.

The status is derived, never set by hand:

* **Drafting** -- the queue still has work for one of its listings.
* **Stopped** -- **Cancel batch** left work undrafted (Resume is on the
  summary).
* **Complete** -- every listing it created, and still has, is reviewed.
* **In review** -- anything else: drafting is over and a listing waits.

*Staging* is a staging session's, which has no batch rows yet.

**Failures are not a status.** A row whose creation or AI failed is a count
beside the progress (*2 need retry*), so a batch with one failure still
reads as Drafting or In review. A listing whose AI failed still exists and
still has to be reviewed -- by hand, if the seller finishes it themselves --
so it holds Complete back exactly as any unreviewed listing does; a row that
was never created has no listing to review, and holds nothing back.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from etsy_listings.batches.records import DRAFTING, AiState, BatchRow, has_listing

BatchStatus = Literal["drafting", "in_review", "complete", "stopped"]

_UNDRAFTED: frozenset[AiState | None] = frozenset({"stopped", "cancelled"})


@dataclass(frozen=True)
class Standing:
    status: BatchStatus
    listings: int
    """Rows with a listing: created and not deleted."""
    drafted: int
    reviewed: int
    undrafted: int
    """Listings **Cancel batch** left for Resume."""
    failures: int
    """Rows needing Retry: creation or AI failed, the listing not deleted."""


def standing(rows: Sequence[BatchRow]) -> Standing:
    live = [row for row in rows if has_listing(row)]
    reviewed = sum(row.reviewed for row in live)
    undrafted = sum(row.ai in _UNDRAFTED for row in live)
    status: BatchStatus
    if any(row.ai in DRAFTING for row in live):
        status = "drafting"
    elif live and reviewed == len(live):
        # Before Stopped: a listing the seller reviewed after a Cancel batch
        # is one they chose to finish without AI (spec, *Review workflow*).
        status = "complete"
    elif undrafted:
        status = "stopped"
    else:
        # Also a batch with no listing left at all: Complete would claim a
        # review that never happened.
        status = "in_review"
    return Standing(
        status=status,
        listings=len(live),
        drafted=sum(row.ai == "done" for row in live),
        reviewed=reviewed,
        undrafted=undrafted,
        failures=sum(
            row.creation == "failed" or (has_listing(row) and row.ai == "failed") for row in rows
        ),
    )

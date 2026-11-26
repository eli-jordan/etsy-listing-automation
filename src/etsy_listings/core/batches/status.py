from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from etsy_listings.core.batches.records import DRAFTING, AiState, BatchRow, has_listing

BatchStatus = Literal["drafting", "in_review", "complete", "stopped"]

_UNDRAFTED: frozenset[AiState | None] = frozenset({"stopped", "cancelled"})


@dataclass(frozen=True)
class Standing:
    status: BatchStatus
    listings: int
    drafted: int
    reviewed: int
    undrafted: int
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
        status = "complete"
    elif undrafted:
        status = "stopped"
    else:
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

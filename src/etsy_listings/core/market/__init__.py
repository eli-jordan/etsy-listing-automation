"""Market research: three buyer queries in, twenty scored comparable
listings, a ranked phrase list and a market-data block out.

Withheld: the disk adapters ``cache`` and ``snapshot``, imported by their
module names; and ``scoring`` and ``phrases``, the pure maths behind
:func:`research`. A caller wanting a score or a phrase list gets it from a
result, so there is one way to compute each.
"""

from __future__ import annotations

from etsy_listings.core.market.block import MARKET_BEGIN, MARKET_END, lead, market_block
from etsy_listings.core.market.models import MarketResult, PhraseScore, ScoredListing
from etsy_listings.core.market.research import (
    MarketResearchError,
    ResearchCancelledError,
    ResearchSettings,
    research,
)

__all__ = [
    "MARKET_BEGIN",
    "MARKET_END",
    "MarketResearchError",
    "MarketResult",
    "PhraseScore",
    "ResearchCancelledError",
    "ResearchSettings",
    "ScoredListing",
    "lead",
    "market_block",
    "research",
]

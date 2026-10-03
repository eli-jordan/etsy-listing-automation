"""Market research: three buyer queries in, twenty scored comparable
listings, a ranked phrase list and a market-data block out (features/market-seo-20260924/spec.md,
*Market search*, *Scoring* and *What the proposal sees*).

Research results are in memory. Disk cache/snapshot adapters are imported
by their own module names. MarketWeights is owned by config and re-exported
here for compatibility; settings loading never imports market.

- ``market.cache`` -- :class:`~etsy_listings.core.market.cache.CachedEtsyMarketClient`,
  the 7-day caches wrapped around any
  :class:`~etsy_listings.core.clients.etsy.market.EtsyMarketClient`;
- ``market.snapshot`` -- :class:`~etsy_listings.core.market.snapshot.MarketSnapshot`
  and its ``save``/``load``, the latest research per listing.

- ``research`` -- :func:`research`, the whole search, filter, stats and
  score pipeline; :class:`MarketResearchError` (the *Etsy market search
  failed* message) and :class:`ResearchCancelled`.
- ``models`` -- :class:`MarketResult`, :class:`ScoredListing`,
  :class:`PhraseScore` and :class:`MarketWeights`.
- ``block`` -- :func:`market_block`, the delimited text the proposal
  prompt receives, and :func:`lead`, a description's first sentence.

Withheld: ``scoring`` and ``phrases``, the pure maths behind :func:`research`.
A caller wanting a score or a phrase list gets it from a result, so there is
one way to compute each.
"""

from __future__ import annotations

from etsy_listings.core.market.block import MARKET_BEGIN, MARKET_END, lead, market_block
from etsy_listings.core.market.models import MarketResult, MarketWeights, PhraseScore, ScoredListing
from etsy_listings.core.market.research import MarketResearchError, ResearchCancelled, research

__all__ = [
    "MARKET_BEGIN",
    "MARKET_END",
    "MarketResearchError",
    "MarketResult",
    "MarketWeights",
    "PhraseScore",
    "ResearchCancelled",
    "ScoredListing",
    "lead",
    "market_block",
    "research",
]

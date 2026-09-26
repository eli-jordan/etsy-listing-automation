"""Market research: three buyer queries in, twenty scored comparable
listings, a ranked phrase list and a market-data block out (market-seo.md,
*Market search*, *Scoring* and *What the proposal sees*).

The names below are all in memory, and nothing here knows about HTTP or the
UI. The two modules that touch disk are imported by their own names, never
re-exported here, because they need the workspace -- and the workspace's
``settings.yaml`` loader imports :class:`MarketWeights` from this package:

- ``market.cache`` -- :class:`~etsy_listings.market.cache.CachedEtsyMarketClient`,
  the 7-day caches wrapped around any
  :class:`~etsy_listings.clients.etsy.market.EtsyMarketClient`;
- ``market.snapshot`` -- :class:`~etsy_listings.market.snapshot.MarketSnapshot`
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

from etsy_listings.market.block import MARKET_BEGIN, MARKET_END, lead, market_block
from etsy_listings.market.models import MarketResult, MarketWeights, PhraseScore, ScoredListing
from etsy_listings.market.research import MarketResearchError, ResearchCancelled, research

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

"""Market research: three buyer queries in, twenty scored comparable
listings, a ranked phrase list and a market-data block out (market-seo.md,
*Market search*, *Scoring* and *What the proposal sees*).

All in memory. Nothing here writes a file or holds a cache -- that is PR 3's
snapshot store and cached client, wrapped around the same
:class:`~etsy_listings.clients.etsy.market.EtsyMarketClient` -- and nothing
here knows about HTTP or the UI.

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

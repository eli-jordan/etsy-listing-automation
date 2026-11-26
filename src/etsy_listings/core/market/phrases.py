from __future__ import annotations

from collections.abc import Sequence

from etsy_listings.core.market.models import PhraseScore, ScoredListing

PHRASE_LIMIT = 40
"""How many phrases are listed (features/market-seo-20260924/spec.md)."""


def normalise(tag: str) -> str:
    return " ".join(tag.casefold().split())


def rank_phrases(
    listings: Sequence[ScoredListing], *, limit: int = PHRASE_LIMIT
) -> tuple[PhraseScore, ...]:
    """The top ``limit`` phrases, best first.

    Ordered by score, then by how many listings use the phrase, then
    alphabetically -- so the list is the same however the listings arrived.
    A listing using a tag twice (in two spellings) counts once.
    """
    counts: dict[str, int] = {}
    sums: dict[str, float] = {}
    for listing in listings:
        for phrase in {normalise(tag) for tag in listing.tags} - {""}:
            counts[phrase] = counts.get(phrase, 0) + 1
            sums[phrase] = sums.get(phrase, 0.0) + listing.score_raw
    best = max(sums.values(), default=0.0)
    ranked = sorted(sums, key=lambda phrase: (-sums[phrase], -counts[phrase], phrase))
    return tuple(
        PhraseScore(
            phrase=phrase,
            listings=counts[phrase],
            score=sums[phrase] / best if best > 0 else 0.0,
        )
        for phrase in ranked[:limit]
    )

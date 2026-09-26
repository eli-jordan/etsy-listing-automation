"""The ranked phrase list (market-seo.md, *What the proposal sees*, part 1).

For each tag the scored listings use: how many use it, and the sum of their
scores normalised so the best phrase is 1. Code does the counting and
weighting because a model is unreliable at counting across twenty blocks of
text.
"""

from __future__ import annotations

from collections.abc import Sequence

from etsy_listings.market.models import PhraseScore, ScoredListing

PHRASE_LIMIT = 40
"""How many phrases are listed (market-seo.md)."""


def normalise(tag: str) -> str:
    """A tag as one phrase: lower-cased, whitespace collapsed. ``Hiking
    Shirt`` and ``hiking  shirt`` are what a buyer types the same way."""
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

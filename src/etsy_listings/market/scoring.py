"""The scoring maths, pure (market-seo.md, *Scoring*).

Each metric becomes a 0-1 **percentile within the set being scored**: a
single viral listing then cannot swamp the rest, and a favourite count and a
star rating can be added together. The weighted sum of those percentiles,
divided by the total weight, is a listing's score.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence

from etsy_listings.market.models import METRICS, MarketWeights, Metric


def percentiles(values: Sequence[float | None]) -> list[float]:
    """Each value's position in the set, 0 for the worst and 1 for the best,
    in the order given.

    Ties share the average of the positions they occupy, so two equal
    listings never differ by the accident of which came first. A single
    value, or a set that is all one value, is therefore 0.5 -- the middle,
    not a claim to be the best.

    ``None`` is a signal that is missing -- a shop with no rating in the past
    year, a listing whose age Etsy did not say -- and ranks below every real
    value, zero included (the spec's "counts as lowest").
    """
    count = len(values)
    if count == 0:
        return []
    if count == 1:
        return [0.5]
    # None sorts first: -inf is below every real value, including 0.
    keys = [-math.inf if value is None else value for value in values]
    order = sorted(range(count), key=lambda index: keys[index])
    result = [0.0] * count
    start = 0
    while start < count:
        end = start
        while end + 1 < count and keys[order[end + 1]] == keys[order[start]]:
            end += 1
        shared = (start + end) / 2 / (count - 1)
        for position in range(start, end + 1):
            result[order[position]] = shared
        start = end + 1
    return result


def rescaled(weights: MarketWeights, *, exclude: Collection[Metric] = ()) -> dict[Metric, float]:
    """The weights left after ``exclude``, rescaled to sum to 1.

    The preliminary ranking excludes reviews -- the one signal that costs a
    call per listing -- and ranks on the rest (market-seo.md, *Stats*). When
    nothing is left to weigh, every weight is 0 and the caller's tie-break
    (search position) decides alone.
    """
    kept = [metric for metric in METRICS if metric not in exclude]
    total = sum(weights.of(metric) for metric in kept)
    if total == 0:
        return dict.fromkeys(kept, 0.0)
    return {metric: weights.of(metric) / total for metric in kept}


def weighted(
    metrics: dict[Metric, Sequence[float | None]], weights: dict[Metric, float]
) -> list[float]:
    """Each listing's score, 0-1: the sum over ``weights`` of its percentile
    for that metric times the (already rescaled) weight."""
    count = len(next(iter(metrics.values()), ()))
    scores = [0.0] * count
    for metric, weight in weights.items():
        for index, share in enumerate(percentiles(metrics[metric])):
            scores[index] += weight * share
    return scores


def display_score(raw: float) -> int:
    """A 0-1 score as the panel's whole number out of 100, halves rounded
    up -- Python's own ``round`` would show 87.5 as 88 but 12.5 as 12."""
    return math.floor(raw * 100 + 0.5)

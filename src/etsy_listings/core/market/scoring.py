from __future__ import annotations

import math
from collections.abc import Collection, Sequence

from etsy_listings.core.config.market_weights import METRICS, MarketWeights, Metric


def _last_tied(keys: list[float], order: list[int], start: int) -> int:
    end = start
    while end + 1 < len(order) and keys[order[end + 1]] == keys[order[start]]:
        end += 1
    return end


def percentiles(values: Sequence[float | None]) -> list[float]:
    """Each value's percentile in the given order: 0 worst, 1 best, ties
    share their average position, and ``None`` ranks below every value."""
    count = len(values)
    if count == 0:
        return []
    if count == 1:
        return [0.5]
    keys = [-math.inf if value is None else value for value in values]
    order = sorted(range(count), key=lambda index: keys[index])
    result = [0.0] * count
    start = 0
    while start < count:
        end = _last_tied(keys, order, start)
        shared = (start + end) / 2 / (count - 1)
        for position in range(start, end + 1):
            result[order[position]] = shared
        start = end + 1
    return result


def rescaled(weights: MarketWeights, *, exclude: Collection[Metric] = ()) -> dict[Metric, float]:
    """The weights left after ``exclude``, rescaled to sum to 1, or all 0
    when nothing is left to weigh."""
    kept = [metric for metric in METRICS if metric not in exclude]
    total = sum(weights.of(metric) for metric in kept)
    if total == 0:
        return dict.fromkeys(kept, 0.0)
    return {metric: weights.of(metric) / total for metric in kept}


def weighted(
    metrics: dict[Metric, Sequence[float | None]], weights: dict[Metric, float]
) -> list[float]:
    count = len(next(iter(metrics.values()), ()))
    scores = [0.0] * count
    for metric, weight in weights.items():
        for index, share in enumerate(percentiles(metrics[metric])):
            scores[index] += weight * share
    return scores


def display_score(raw: float) -> int:
    """A 0-1 score out of 100, halves up (``round`` rounds half to even)."""
    return math.floor(raw * 100 + 0.5)

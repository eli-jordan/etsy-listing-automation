"""One-off, uncached live FX-rate fetch for ``new``'s pricing-plan wizard only.

This is **not** the PRD's deferred full-margin-model FX module (PRD 10b) --
that one owns a TTL-cached ``.cache/fx.json`` and supersedes this once built.
Deliberately not named/placed as that reserved future package (``fx/``): do
not add caching here, that is exactly the scope this file exists to stay
out of.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx

FRANKFURTER_URL = "https://api.frankfurter.app/latest"


@dataclass(frozen=True)
class FxRate:
    rate: Decimal
    """1 USD == ``rate`` units of the target currency."""
    source: str
    fetched_at: datetime


def fetch_usd_to(target_currency: str, *, client: httpx.Client | None = None) -> FxRate | None:
    """``None`` on any failure -- fail-soft, never raises."""
    http = client or httpx.Client(timeout=10.0)
    try:
        response = http.get(FRANKFURTER_URL, params={"from": "USD", "to": target_currency})
        response.raise_for_status()
        payload = response.json()
        rate = Decimal(str(payload["rates"][target_currency]))
        return FxRate(rate=rate, source="frankfurter.app", fetched_at=datetime.now(UTC))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None

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

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
"""The ``.dev`` host, and the versioned path. ``api.frankfurter.app/latest``
-- what this asked for until it stopped working -- now answers 301 to exactly
this URL.

The redirect is why ``follow_redirects`` is on below, and the two are not
alternatives: hard-coding the destination keeps the request one hop, and
following redirects means the *next* move degrades to a slow success rather
than to a silent one. A 3xx is not an error, but ``raise_for_status`` treats
it as one, so an unfollowed redirect landed in the fail-soft branch and wrote
a whole pricing plan of zeroes -- the failure this pairing exists to prevent.
"""


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
        response = http.get(
            FRANKFURTER_URL,
            params={"from": "USD", "to": target_currency},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        rate = Decimal(str(payload["rates"][target_currency]))
        return FxRate(rate=rate, source="frankfurter.dev", fetched_at=datetime.now(UTC))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None

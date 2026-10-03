"""One-off, uncached live FX-rate fetch for ``new``'s pricing-plan wizard only.

The wizard uses one current rate while choosing a saved retail price. It does
not cache rates or calculate a full margin model; deployment uses the saved
amount without another conversion. The original broader FX design remains
unbuilt, so it is not a dependency of this helper.
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

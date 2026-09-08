"""Printify's undocumented product-catalog-service per-variant cost endpoint.

**Not** part of the documented ``CatalogClient`` surface -- no auth, no
official docs, confirmed working against a live 238-variant response
(blueprint 706 / provider 29) but liable to change or vanish without notice.
Every caller in ``new``'s pricing-plan wizard must treat this as fail-soft:
any network error, non-200, JSON-shape mismatch or missing field degrades to
a blank price for the affected variant(s), never an exception that aborts
``new`` (PRD 35).

``data[].id`` in the response matches the variant ``id`` from the public,
documented ``variants.json`` catalog endpoint already fetched by
``catalog.variants()`` -- join on ``id`` to recover human-readable
``{color, size}``; this endpoint's own ``options: [4802, 14]`` are opaque
numeric option IDs, not directly usable.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://printify.com/product-catalog-service/api/v2"

DEFAULT_DECORATION_METHOD = "dtg"
"""Hardcoded, not derived from the provider's offered methods (PRD risk
item). Confirmed correct for this workspace's real garment/provider; wrong
for a provider using a different method just fails soft to blank prices,
per the module-wide policy above."""


def parse_variant_costs(payload: dict[str, Any]) -> dict[int, int]:
    """``variant_id -> manufacturing cost``, USD cents. ``{}`` on any shape
    failure -- never raises."""
    out: dict[int, int] = {}
    try:
        for entry in payload.get("data", []):
            try:
                out[int(entry["id"])] = int(entry["costs"][0]["result"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue  # skip this one variant, keep going
    except (KeyError, TypeError, AttributeError):
        return {}
    return out


def fetch_variant_costs(
    blueprint_id: int,
    provider_id: int,
    *,
    decoration_method: str = DEFAULT_DECORATION_METHOD,
    client: httpx.Client | None = None,
) -> dict[int, int]:
    """``{}`` on any failure -- network, HTTP status, or JSON shape -- never
    raises. The wizard step calling this must remain usable with no result."""
    http = client or httpx.Client(timeout=15.0)
    try:
        response = http.get(
            f"{BASE_URL}/blueprints/{blueprint_id}/print-providers/{provider_id}/variants",
            params={"decoration_method": decoration_method},
        )
        response.raise_for_status()
        return parse_variant_costs(response.json())
    except (httpx.HTTPError, ValueError):
        return {}

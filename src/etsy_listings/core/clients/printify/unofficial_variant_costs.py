"""Printify's undocumented product-catalog-service per-variant cost endpoint
(ADR-0016)."""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://printify.com/product-catalog-service/api/v2"

DEFAULT_DECORATION_METHOD = "dtg"
"""Hardcoded, not derived from the provider's offered methods. Confirmed correct for this
workspace's real garment/provider; wrong
for a provider using a different method just fails soft to blank prices,
per ADR-0016's fail-soft policy."""


def parse_variant_costs(payload: dict[str, Any]) -> dict[int, int]:
    out: dict[int, int] = {}
    try:
        for entry in payload.get("data", []):
            try:
                out[int(entry["id"])] = int(entry["costs"][0]["result"])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
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

"""Real HTTP implementation of :class:`CatalogClient` against Printify's public,
unauthenticated catalog endpoints. Never exercised in unit/behaviour tests --
covered only by the manual, env-gated ``-m e2e`` layer."""

from __future__ import annotations

import httpx

from etsy_listings.catalog.client import CatalogClient
from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Variant,
    VariantOptions,
    VariantSet,
)

BASE_URL = "https://api.printify.com/v1/catalog"


class HttpCatalogClient(CatalogClient):
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=30.0)

    def blueprints(self) -> list[Blueprint]:
        response = self._client.get("/blueprints.json")
        response.raise_for_status()
        return [Blueprint.model_validate(item) for item in response.json()]

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]:
        response = self._client.get(f"/blueprints/{blueprint_id}/print_providers.json")
        response.raise_for_status()
        return [PrintProvider.model_validate(item) for item in response.json()]

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet:
        response = self._client.get(
            f"/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        )
        response.raise_for_status()
        payload = response.json()
        variants = tuple(
            Variant(
                id=item["id"],
                title=item["title"],
                options=VariantOptions.model_validate(item["options"]),
            )
            for item in payload["variants"]
        )
        placeholders = tuple(
            PrintAreaPlaceholder.model_validate(item) for item in payload.get("placeholders", [])
        )
        return VariantSet(variants=variants, placeholders=placeholders)

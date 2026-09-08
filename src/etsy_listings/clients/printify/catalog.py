"""Printify's read-only reference data over HTTP: blueprints, print providers,
variants, shipping.

Exercised by the contract layer through ``httpx``'s mock transport (payload
shape, auth headers, error decoding); the env-gated ``-m e2e`` layer is what
ever touches the real API.

**These endpoints are authenticated.** They were documented as "public,
unauthenticated" and they are not: every ``/v1/catalog/*.json`` call needs a
personal access token with the ``catalog.read`` scope, and without one
Printify answers ``401 Unauthorized``. That mistake is why ``new`` died on a
raw httpx traceback.

Everything between a path and a decoded response -- the token, the retries,
the error shapes -- is :mod:`~etsy_listings.clients.printify.transport`,
shared with the write side. What is not shared is the surface: this class
satisfies :class:`CatalogClient` and nothing else, so a caller holding one
cannot reach a call that creates a product.
"""

from __future__ import annotations

from etsy_listings.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingCost,
    ShippingProfile,
    ShippingRates,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.clients.printify.protocol import CatalogClient
from etsy_listings.clients.printify.transport import Transport


class HttpCatalogClient(CatalogClient):
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def blueprints(self) -> list[Blueprint]:
        response = self._transport.get("/v1/catalog/blueprints.json")
        return [Blueprint.model_validate(item) for item in response.json()]

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]:
        response = self._transport.get(
            f"/v1/catalog/blueprints/{blueprint_id}/print_providers.json"
        )
        return [PrintProvider.model_validate(item) for item in response.json()]

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet:
        response = self._transport.get(
            f"/v1/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json"
        )
        payload = response.json()
        # `placeholders` is nested inside each variant -- the response has no
        # top-level one, and reading it as though it did silently produced a
        # set with no print areas at all. See `Variant.placeholders`.
        variants = tuple(
            Variant(
                id=item["id"],
                title=item["title"],
                options=VariantOptions.model_validate(item["options"]),
                placeholders=tuple(
                    PrintAreaPlaceholder.model_validate(p) for p in item.get("placeholders", [])
                ),
            )
            for item in payload["variants"]
        )
        return VariantSet(variants=variants)

    def shipping(self, blueprint_id: int, provider_id: int) -> ShippingRates:
        response = self._transport.get(
            f"/v1/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/shipping.json"
        )
        payload = response.json()
        profiles = tuple(
            ShippingProfile(
                variant_ids=tuple(item["variant_ids"]),
                first_item=ShippingCost.model_validate(item["first_item"]),
                additional_items=ShippingCost.model_validate(item["additional_items"]),
            )
            for item in payload.get("profiles", [])
        )
        return ShippingRates(profiles=profiles)

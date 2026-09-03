"""In-memory :class:`CatalogClient` for tests. No network, ever."""

from __future__ import annotations

from etsy_listings.catalog.client import CatalogClient
from etsy_listings.catalog.models import Blueprint, PrintProvider, VariantSet


class FakeCatalogClient(CatalogClient):
    def __init__(
        self,
        blueprints: list[Blueprint],
        providers_by_blueprint: dict[int, list[PrintProvider]],
        variants_by_key: dict[tuple[int, int], VariantSet],
    ) -> None:
        self._blueprints = blueprints
        self._providers_by_blueprint = providers_by_blueprint
        self._variants_by_key = variants_by_key

    def blueprints(self) -> list[Blueprint]:
        return list(self._blueprints)

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]:
        return list(self._providers_by_blueprint.get(blueprint_id, []))

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet:
        key = (blueprint_id, provider_id)
        if key not in self._variants_by_key:
            raise KeyError(
                f"no fixture variants for blueprint={blueprint_id} provider={provider_id}"
            )
        return self._variants_by_key[key]

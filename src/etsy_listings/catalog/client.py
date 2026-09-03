"""The catalog read boundary. Any concrete implementation (real HTTP, TTL-cached,
or a test fake) satisfies this without the rest of the codebase knowing which."""

from __future__ import annotations

from typing import Protocol

from etsy_listings.catalog.models import Blueprint, PrintProvider, VariantSet


class CatalogClient(Protocol):
    def blueprints(self) -> list[Blueprint]: ...

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]: ...

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet: ...

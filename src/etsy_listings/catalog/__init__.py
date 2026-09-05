"""Printify's reference data: blueprints, print providers, variants, shipping.

Read-only and shop-agnostic. Nothing here is authenticated beyond the
``catalog.read`` token, nothing is scoped to a shop, and nothing writes --
creating products is Phase 2's job, in ``clients/printify``.

:class:`CatalogClient` is the protocol; :class:`HttpCatalogClient` talks to
Printify, :class:`CachedCatalogClient` wraps any client with the TTL disk
cache (PRD 22), and :class:`FakeCatalogClient` is what behaviour tests use.
They compose: the CLI builds ``CachedCatalogClient(HttpCatalogClient(token))``.
"""

from etsy_listings.catalog.cache import DEFAULT_TTL, CachedCatalogClient
from etsy_listings.catalog.client import CatalogClient
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.catalog.http import CatalogAuthError, HttpCatalogClient
from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingProfile,
    ShippingRates,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.catalog.resolve import (
    AmbiguousBlueprintError,
    CatalogResolutionError,
    resolve_blueprint,
    resolve_print_provider,
)

__all__ = [
    # The protocol, and the three things that satisfy it.
    "CatalogClient",
    "HttpCatalogClient",
    "CachedCatalogClient",
    "FakeCatalogClient",
    "DEFAULT_TTL",
    "CatalogAuthError",
    # What the catalog returns.
    "Blueprint",
    "PrintProvider",
    "Variant",
    "VariantOptions",
    "VariantSet",
    "PrintAreaPlaceholder",
    "ShippingProfile",
    "ShippingRates",
    # Name -> id resolution, with an error that lists the near misses.
    "AmbiguousBlueprintError",
    "CatalogResolutionError",
    "resolve_blueprint",
    "resolve_print_provider",
]

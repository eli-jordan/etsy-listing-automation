"""Everything this tool says to Printify.

:class:`CatalogClient` is the read-only, shop-agnostic reference data;
:class:`PrintifyClient` is the shop-scoped half that writes. A caller holding
the first cannot reach a call that creates a product, because the method is
not on the type it was handed.

**Nothing caches on the write side, deliberately.** A shop's products are the
state this tool is converging on, and a cached read of them would make ``plan``
report a diff against a stale world.

Deliberately withheld: ``unofficial_variant_costs``, the undocumented cost
endpoint only the pricing-plan wizard may call.
"""

from etsy_listings.core.clients.printify.cache import DEFAULT_TTL, CachedCatalogClient
from etsy_listings.core.clients.printify.catalog import HttpCatalogClient
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingProfile,
    ShippingRates,
    Shop,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.core.clients.printify.products import HttpPrintifyClient
from etsy_listings.core.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.core.clients.printify.resolve import (
    AmbiguousBlueprintError,
    CatalogResolutionError,
    ResolvedVariant,
    UnknownSizeError,
    VariantResolution,
    resolve_blueprint,
    resolve_print_provider,
    resolve_variants,
)
from etsy_listings.core.clients.printify.transport import (
    BASE_URL,
    PrintifyApiError,
    PrintifyAuthError,
    Transport,
)

__all__ = [
    "BASE_URL",
    "DEFAULT_TTL",
    "AmbiguousBlueprintError",
    "Blueprint",
    "CachedCatalogClient",
    "CatalogClient",
    "CatalogResolutionError",
    "FakeCatalogClient",
    "FakePrintifyClient",
    "HttpCatalogClient",
    "HttpPrintifyClient",
    "PrintAreaPlaceholder",
    "PrintProvider",
    "PrintifyApiError",
    "PrintifyAuthError",
    "PrintifyClient",
    "ResolvedVariant",
    "ShippingProfile",
    "ShippingRates",
    "Shop",
    "Transport",
    "UnknownSizeError",
    "Variant",
    "VariantOptions",
    "VariantResolution",
    "VariantSet",
    "resolve_blueprint",
    "resolve_print_provider",
    "resolve_variants",
]

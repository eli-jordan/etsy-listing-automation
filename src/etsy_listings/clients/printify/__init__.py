"""Everything this tool says to Printify.

One host, one token, one package -- and, inside it, two protocols that do not
overlap. :class:`CatalogClient` is the read-only, shop-agnostic reference data
(blueprints, print providers, variants, shipping); :class:`PrintifyClient` is
the shop-scoped half that writes. A caller holding the first cannot reach a
call that creates a product, because the method is not on the type it was
handed.

These were two packages, ``catalog/`` and ``clients/printify/``, and the split
was defended as an authority boundary. The boundary is real and is kept; what
it did not need was a second copy of the plumbing. Both halves carried their
own ``TokenSource``, lazy token resolve, ``401/403`` branch, auth error, base
URL and ``httpx.Client`` -- and the copies had already drifted, the catalog
reader having no retries at all while the identical failure on a write rode
out its backoff (A21). :mod:`~etsy_listings.clients.printify.transport` is now
the one implementation, and the authority lives where it always belonged, in
the protocols.

The parts:

``transport``   token, retries, auth and error decoding -- the shared half
``protocol``    the two boundaries; the split that actually matters
``models``      what Printify returns, reference data and shop state alike
``catalog``     :class:`CatalogClient` over HTTP
``products``    :class:`PrintifyClient` over HTTP
``cache``       TTL disk cache; wraps a catalog client, and only a catalog one
``resolve``     name -> id, the only place a config name becomes an integer
``fakes``       in-memory implementations of both, for the behaviour suite

**Nothing caches on the write side, deliberately.** A shop's products are the
state this tool is converging on, and a cached read of them would make ``plan``
report a diff against a stale world.
"""

from etsy_listings.clients.printify.cache import DEFAULT_TTL, CachedCatalogClient
from etsy_listings.clients.printify.catalog import HttpCatalogClient
from etsy_listings.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.clients.printify.models import (
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
from etsy_listings.clients.printify.products import HttpPrintifyClient
from etsy_listings.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.clients.printify.resolve import (
    AmbiguousBlueprintError,
    CatalogResolutionError,
    ResolvedVariant,
    UnknownSizeError,
    VariantResolution,
    resolve_blueprint,
    resolve_print_provider,
    resolve_variants,
)
from etsy_listings.clients.printify.transport import (
    BASE_URL,
    PrintifyApiError,
    PrintifyAuthError,
    Transport,
)

__all__ = [
    # The shared connection.
    "Transport",
    "BASE_URL",
    "PrintifyAuthError",
    "PrintifyApiError",
    # The two boundaries, and what satisfies each.
    "CatalogClient",
    "HttpCatalogClient",
    "CachedCatalogClient",
    "FakeCatalogClient",
    "DEFAULT_TTL",
    "PrintifyClient",
    "HttpPrintifyClient",
    "FakePrintifyClient",
    # What Printify returns.
    "Blueprint",
    "PrintProvider",
    "Variant",
    "VariantOptions",
    "VariantSet",
    "PrintAreaPlaceholder",
    "ShippingProfile",
    "ShippingRates",
    "Shop",
    # Name -> id resolution, with an error that lists the near misses.
    "AmbiguousBlueprintError",
    "CatalogResolutionError",
    "UnknownSizeError",
    "resolve_blueprint",
    "resolve_print_provider",
    # Colour slug x size -> the integer ids Printify sells by.
    "resolve_variants",
    "ResolvedVariant",
    "VariantResolution",
]

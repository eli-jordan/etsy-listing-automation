"""In-memory vendor clients behind ``create_app``'s ``clients=`` seam.

:class:`FakeClients` holds one fake per vendor client, and its
:meth:`~FakeClients.factories` answer with whichever fake it holds *when
asked*, so a test can swap one after the app is built -- the ``client``
fixture builds the app before the test body says what Etsy should report.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from etsy_listings.core.application.dependencies import ClientFactories
from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient, FakeEtsyShopClient
from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.clients.etsy.market import EtsyMarketClient
from etsy_listings.core.clients.etsy.shops import EtsyShopClient
from etsy_listings.core.clients.printify import CatalogClient, PrintifyClient
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient


def _empty_catalog() -> CatalogClient:
    return FakeCatalogClient([], {}, {})


@dataclass
class FakeClients:
    """The fakes a host builds its clients from. ``etsy_market`` is ``None``
    by default: a workspace with no Etsy app key, as the fixture is."""

    etsy_listing: EtsyListingClient = field(default_factory=FakeEtsyListingClient)
    etsy_shop: EtsyShopClient = field(default_factory=FakeEtsyShopClient)
    printify: PrintifyClient = field(default_factory=FakePrintifyClient)
    catalog: CatalogClient = field(default_factory=_empty_catalog)
    etsy_market: EtsyMarketClient | None = None

    def factories(self) -> ClientFactories:
        return ClientFactories(
            etsy_listing=lambda _root: self.etsy_listing,
            etsy_shop=lambda _root: self.etsy_shop,
            printify=lambda _workspace: self.printify,
            catalog=lambda _workspace: self.catalog,
            etsy_market=lambda _workspace: self.etsy_market,
        )

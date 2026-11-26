"""The seams a host supplies to core's operations and coordinators, each a
callable shape a test replaces with a fake."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.clients.etsy.market import EtsyMarketClient
from etsy_listings.core.clients.etsy.shops import EtsyShopClient
from etsy_listings.core.clients.printify import CatalogClient, PrintifyClient
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace

EtsyStates = Callable[[Sequence[int]], Mapping[int, str | None]]
"""Etsy's ``state`` for each listing id asked about, ``None`` where unknown.

Status, gestures and the published-deletion refusal all turn on it, and only
Etsy knows it. Asked once per read with every id the read needs, so a table
costs one round trip; a lookup that cannot ask (no credentials, no shop)
answers ``None``, which reads as not published."""

ContextFactory = Callable[[Workspace, EventSink | None], RunContext]
"""How a deployment run's :class:`~etsy_listings.core.engine.context.RunContext`
is built (ADR-0041).
``connections.run_context`` is the default every real server uses; a test
wires one to in-memory fakes instead, by swapping this one callable --
nothing in the executor knows how a client is assembled."""

MarketClientFactory = Callable[[Workspace], EtsyMarketClient | None]
"""The uncached market client, or ``None`` when the workspace has no Etsy
key. The AI runner wraps it in the workspace's caches itself."""


def default_market_client(workspace: Workspace) -> EtsyMarketClient | None:
    if connections.etsy_app_key(workspace.root) is None:
        return None
    return connections.etsy_market_client(workspace.root)


@dataclass(frozen=True)
class ClientFactories:
    """The vendor clients a host's handlers build, one per workspace.
    Building one resolves no credential, so any is safe before ``auth`` has
    run; which protocol a field answers is the caller's authority (ADR-0024).
    """

    etsy_listing: Callable[[Path], EtsyListingClient]
    """Signed-in listing reads and writes, shop sections and lookups."""
    etsy_shop: Callable[[Path], EtsyShopClient]
    """Unscoped shop lookups; adds a bearer only when someone has signed in."""
    printify: Callable[[Workspace], PrintifyClient]
    """The shop-scoped, writing half of Printify."""
    catalog: Callable[[Workspace], CatalogClient]
    """Blueprints, providers and variants over the workspace's disk cache."""
    etsy_market: MarketClientFactory
    """Read-only market research, or ``None`` with no Etsy app key."""


DEFAULT_CLIENTS = ClientFactories(
    etsy_listing=connections.etsy_listing_client,
    etsy_shop=connections.etsy_shop_client,
    printify=connections.printify_client,
    catalog=connections.catalog_client,
    etsy_market=default_market_client,
)
"""The real clients, built by ``connections``: what every real host passes."""

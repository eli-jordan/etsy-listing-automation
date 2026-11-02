"""The seams a host supplies to core's operations and coordinators.

Each is a callable shape rather than a class to subclass, so the real thing
satisfies it as it stands and a test passes a fake in its place:

* :data:`EtsyStates` -- what listing operations take the UI process's memo of
  Etsy listing states through. The memo is the server's
  (``server/api/etsystate.py``), request-serving read infrastructure that
  stays there (plan, PR 7), and core must never import the server
  (ADR-0052).
* :data:`ContextFactory` -- how ``deploy.deployments.Deployments`` builds a
  run's engine context; ``connections.run_context`` in a real host.
* :data:`MarketClientFactory` -- how ``ai.coordinator.AiCoordinator`` finds
  the uncached Etsy market client; :func:`default_market_client` in a real
  host.
* :class:`ClientFactories` -- how a host builds the Etsy and Printify
  clients its routes, its AI runs and setup's discovery ask through;
  :data:`DEFAULT_CLIENTS` in a real host.
  A record of callables rather than one callable, because a route needs
  more than one vendor's client and a test swaps any of them.

They live here, not beside the worker that calls them, because the deploy
executor and the AI runner are implementation-only (Import Linter's
``protected`` contracts in ``pyproject.toml``): a host names the seam it
fills without importing the machinery behind the coordinator.

Everything else an operation coordinates through is core's own, so it takes
that class directly: the AI run registry, the batch queue, AI readiness and the
deploy-to-AI handoff (``ai/``, since PR 9). One implementation each and no
second one in sight left an interface for them nothing to vary.
"""

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
is built (ADR-0041, decision 7's "contexts are injected").
``connections.run_context`` is the default every real server uses; a test
wires one to in-memory fakes instead, by swapping this one callable --
nothing in the executor knows how a client is assembled."""

MarketClientFactory = Callable[[Workspace], EtsyMarketClient | None]
"""The uncached market client, or ``None`` when the workspace has no Etsy
key. The AI runner wraps it in the workspace's caches itself."""


def default_market_client(workspace: Workspace) -> EtsyMarketClient | None:
    """The real, read-only Etsy market client (the app key only), or
    ``None`` when the workspace has none."""
    if connections.etsy_app_key(workspace.root) is None:
        return None
    return connections.etsy_market_client(workspace.root)


@dataclass(frozen=True)
class ClientFactories:
    """The vendor clients a host's handlers build, one per workspace.

    A host takes this rather than calling ``connections`` itself, so a test
    hands it factories over the in-memory fakes instead of patching module
    attributes. Each field is one of ``connections``' factories in a real
    host, and building a client resolves no credential (the credential
    invariant), so any of them is safe to call before ``auth`` has run.
    Which protocol a field answers is the caller's authority (ADR-0024).
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

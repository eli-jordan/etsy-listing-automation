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

They live here, not beside the worker that calls them, because the deploy
executor and the AI runner are implementation-only (Import Linter's
``protected`` contracts in ``pyproject.toml``): a host names the seam it
fills without importing the machinery behind the coordinator.

Everything else an operation coordinates through is core's own, so it takes
that class directly: the template write locks (``workspace_locks.WorkspaceLocks``,
since PR 8), and the AI run registry, the batch queue, AI readiness and the
deploy-to-AI handoff (``ai/``, since PR 9). One implementation each and no
second one in sight left an interface for them nothing to vary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.market import EtsyMarketClient
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

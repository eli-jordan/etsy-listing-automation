"""What a workspace can talk to: one place that builds the clients.

Factories build transports and clients without reading credentials. Printify
tokens, Etsy app keys and signed-in bearers are resolved on each request, so
clients can be built before auth and key rotations take effect without a
restart. Missing credentials fail actionably when a request needs them.

etsy_app_key is an explicit availability query for readiness/setup callers;
it is separate from client construction. Market requests never attach a
bearer, avoiding unnecessary refresh-token rotation.

This module does not verify anything. Proving a credential works is
``core/application/credentials.py``'s job, and it is a separate one: `setup` and `auth` verify
a token the user has just typed, before it is stored, against a client built
here from that token rather than from the file it is not yet in.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import httpx

from etsy_listings.core.clients.etsy.listings import EtsyListingClient, HttpEtsyListingClient
from etsy_listings.core.clients.etsy.market import EtsyMarketClient, HttpEtsyMarketClient
from etsy_listings.core.clients.etsy.oauth import TokenResponse
from etsy_listings.core.clients.etsy.shops import EtsyShopClient, HttpEtsyShopClient
from etsy_listings.core.clients.etsy.tokens import TokenStore, utcnow
from etsy_listings.core.clients.etsy.transport import OAuthClient
from etsy_listings.core.clients.etsy.transport import Transport as EtsyTransport
from etsy_listings.core.clients.printify import (
    CachedCatalogClient,
    CatalogClient,
    HttpCatalogClient,
    HttpPrintifyClient,
    PrintifyClient,
    Transport,
)
from etsy_listings.core.config.secrets import EtsyAppKey, Secrets
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

OAuthFactory = Callable[[str], OAuthClient]
"""How to reach Etsy's token endpoint, given a keystring. Injected only so
`auth`'s tests can drive the whole flow without a socket."""

Clock = Callable[[], datetime]


# ------------------------------------------------------------------ Printify


def printify_transport(root: Path) -> Transport:
    """One connection to Printify, with its token resolved lazily.

    Shared by both clients because it is one host and one token: they differ
    in what they are allowed to *ask*, which is a matter of which protocol the
    caller holds, not of which socket the bytes leave through.
    """

    def token() -> str:
        return Secrets.load(root / layout.ENV_FILE).require_printify_api_token()

    return Transport(token)


def printify_client_for(token: str) -> PrintifyClient:
    """A client speaking for a token the caller already has in hand.

    The verification path, not the run path: `setup` and `auth` both hold a
    token the user has just typed and which is deliberately *not* in the
    ``.env`` yet, because storing an unverified credential produces a
    workspace that looks configured and is not.
    """
    return HttpPrintifyClient(Transport(token))


def catalog_client(workspace: Workspace, *, credentials_root: Path | None = None) -> CatalogClient:
    """Blueprints, providers and variants, over the workspace's disk cache.

    ``credentials_root`` lets the E2E layer borrow a configured workspace's
    token while keeping all derived cache state in its disposable workspace.
    """
    return CachedCatalogClient(
        HttpCatalogClient(printify_transport(credentials_root or workspace.root)),
        workspace.catalog_cache_dir(),
    )


def printify_client(
    workspace: Workspace, *, credentials_root: Path | None = None
) -> PrintifyClient:
    """The shop-scoped, writing half of the Printify surface."""
    return HttpPrintifyClient(printify_transport(credentials_root or workspace.root))


# ---------------------------------------------------------------------- Etsy


def etsy_tokens_file(root: Path) -> Path:
    return root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE


def etsy_token_store(
    root: Path, *, oauth: OAuthFactory = OAuthClient, now: Clock = utcnow
) -> TokenStore:
    """The store, wired to refresh through whatever keystring is on disk.

    The keystring is resolved *inside* the refresh rather than captured now,
    because `auth --check` builds a store for a workspace that may hold no
    credentials at all, and demanding one to answer "what have I got?" would
    fail the question it was asked.
    """

    def refresh(refresh_token: str) -> TokenResponse:
        app_key = Secrets.load(root / layout.ENV_FILE).require_etsy_app_key()
        return oauth(app_key.keystring).refresh(refresh_token)

    return TokenStore(etsy_tokens_file(root), refresh=refresh, now=now)


def etsy_app_key(root: Path) -> EtsyAppKey | None:
    """The workspace's Etsy app key pair, or ``None`` if it has none.

    Checked without raising, unlike :meth:`Secrets.require_etsy_app_key`: a
    workspace that has never touched Etsy must not be made to configure it
    just to render mockups.

    Half a pair reads as absent, not as an error. `auth etsy` captures the
    keystring and the shared secret in one step, so a lone keystring means an
    interrupted capture -- and "run `auth etsy`", which is what a blocked
    stage already says, is the same remedy either way.
    """
    secrets = Secrets.load(root / layout.ENV_FILE)
    if not (secrets.etsy_keystring and secrets.etsy_shared_secret):
        return None
    return secrets.require_etsy_app_key()


def _etsy_app_key_source(root: Path) -> Callable[[], EtsyAppKey]:
    def app_key() -> EtsyAppKey:
        return Secrets.load(root / layout.ENV_FILE).require_etsy_app_key()

    return app_key


def etsy_transport(root: Path) -> EtsyTransport:
    """Resolve the app key and signed-in bearer on each request."""
    return EtsyTransport(_etsy_app_key_source(root), bearer=etsy_token_store(root).access_token)


def etsy_listing_client(root: Path) -> EtsyListingClient:
    """Build the listing connection without demanding credentials."""
    return HttpEtsyListingClient(etsy_transport(root))


def etsy_shop_client(root: Path) -> EtsyShopClient:
    """Unscoped lookups, adding a bearer only if one exists at request time."""
    store = etsy_token_store(root)

    def bearer() -> str | None:
        return store.access_token() if store.load() is not None else None

    return HttpEtsyShopClient(EtsyTransport(_etsy_app_key_source(root), bearer=bearer))


def etsy_market_client(root: Path, *, http: httpx.Client | None = None) -> EtsyMarketClient:
    """Read-only research with a lazy app key and no rotating bearer."""
    return HttpEtsyMarketClient(EtsyTransport(_etsy_app_key_source(root), client=http))


# ------------------------------------------------------------------- the run


def run_context(
    workspace: Workspace,
    on_event: EventSink | None = None,
    *,
    credentials_root: Path | None = None,
) -> RunContext:
    """Everything a run may need, none of it demanded up front.

    The optional clients are what let one context serve every phase: a
    workspace with no Printify shop and no Etsy sign-in still plans and still
    renders, and the stages that need a client report themselves blocked
    rather than the run failing to start.

    ``credentials_root`` is the E2E seam for a disposable data workspace that
    borrows a configured workspace's secrets. Only credentials come from it;
    the catalog cache remains under ``workspace``.
    """
    sink = {"on_event": on_event} if on_event is not None else {}
    root = credentials_root or workspace.root
    return RunContext(
        workspace=workspace,
        catalog=catalog_client(workspace, credentials_root=root),
        printify=printify_client(workspace, credentials_root=root),
        etsy=etsy_listing_client(root),
        **sink,
    )

"""Builds every client a workspace talks to; credentials resolve at request time."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
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


def printify_transport(root: Path) -> Transport:
    def token() -> str:
        return Secrets.load(root / layout.ENV_FILE).require_printify_api_token()

    return Transport(token)


def printify_client_for(token: str) -> PrintifyClient:
    return HttpPrintifyClient(Transport(token))


def catalog_client(workspace: Workspace, *, credentials_root: Path | None = None) -> CatalogClient:
    return CachedCatalogClient(
        HttpCatalogClient(printify_transport(credentials_root or workspace.root)),
        workspace.catalog_cache_dir(),
    )


def printify_client(
    workspace: Workspace, *, credentials_root: Path | None = None
) -> PrintifyClient:
    return HttpPrintifyClient(printify_transport(credentials_root or workspace.root))


def etsy_tokens_file(root: Path) -> Path:
    return root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE


def etsy_token_store(
    root: Path, *, oauth: OAuthFactory = OAuthClient, now: Clock = utcnow
) -> TokenStore:

    def refresh(refresh_token: str) -> TokenResponse:
        app_key = Secrets.load(root / layout.ENV_FILE).require_etsy_app_key()
        return oauth(app_key.keystring).refresh(refresh_token)

    return TokenStore(etsy_tokens_file(root), refresh=refresh, now=now)


def etsy_app_key(root: Path) -> EtsyAppKey | None:
    secrets = Secrets.load(root / layout.ENV_FILE)
    if not (secrets.etsy_keystring and secrets.etsy_shared_secret):
        return None
    return secrets.require_etsy_app_key()


def _etsy_app_key_source(root: Path) -> Callable[[], EtsyAppKey]:
    def app_key() -> EtsyAppKey:
        return Secrets.load(root / layout.ENV_FILE).require_etsy_app_key()

    return app_key


def etsy_transport(
    root: Path, *, http: httpx.Client | None = None, oauth: OAuthFactory = OAuthClient
) -> EtsyTransport:
    return EtsyTransport(
        _etsy_app_key_source(root),
        bearer=etsy_token_store(root, oauth=oauth).access_token,
        client=http,
    )


def etsy_listing_client(
    root: Path, *, http: httpx.Client | None = None, oauth: OAuthFactory = OAuthClient
) -> EtsyListingClient:
    return HttpEtsyListingClient(etsy_transport(root, http=http, oauth=oauth))


def etsy_shop_client(
    root: Path, *, http: httpx.Client | None = None, oauth: OAuthFactory = OAuthClient
) -> EtsyShopClient:
    store = etsy_token_store(root, oauth=oauth)

    def bearer() -> str | None:
        return store.access_token() if store.load() is not None else None

    return HttpEtsyShopClient(EtsyTransport(_etsy_app_key_source(root), bearer=bearer, client=http))


def etsy_market_client(root: Path, *, http: httpx.Client | None = None) -> EtsyMarketClient:
    return HttpEtsyMarketClient(EtsyTransport(_etsy_app_key_source(root), client=http))


def run_context(
    workspace: Workspace,
    on_event: EventSink | None = None,
    *,
    credentials_root: Path | None = None,
) -> RunContext:
    root = credentials_root or workspace.root
    ctx = RunContext(
        workspace=workspace,
        catalog=catalog_client(workspace, credentials_root=root),
        printify=printify_client(workspace, credentials_root=root),
        etsy=etsy_listing_client(root),
    )
    return ctx if on_event is None else replace(ctx, on_event=on_event)

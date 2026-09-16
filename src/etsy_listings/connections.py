"""What a workspace can talk to: one place that builds the clients.

Assembling a signed-in Etsy connection takes five steps in a fixed order --
read the ``.env``, decide whether there is a key pair at all, open the token
store at ``.auth/etsy-tokens.json`` with a refresh that can find the keystring
again, hang a transport off the store's access token, and wrap it in a
client. `cli`, `setup`, `auth` and the e2e layer each wrote that sequence out,
which is four places to update when the shape changes and four chances to get
the lazy/eager question wrong -- the question this module exists to answer
once:

**A credential is resolved when it is used, never when a client is built.**
``plan`` constructs a catalog client it may never call, and a workspace that
has only ever rendered mockups has no ``.env`` at all. Demanding a token at
construction time would break every one of them, so Printify's token arrives
through a callable and Etsy's bearer through the store (A22, A23).

**Absent is not broken.** :func:`etsy_listing_client` answers ``None`` for a
workspace that has never run `auth etsy`, because that is an ordinary state of
a Phase 1/2 workspace and the Etsy stages already report it as a blocked
stage naming the command that fixes it. A credential that is genuinely
*missing* where one is required is still reported by name and file, by
``Secrets`` -- never as a raw ``401``.

This module does not verify anything. Proving a credential works is
``credentials.py``'s job, and it is a separate one: `setup` and `auth` verify
a token the user has just typed, before it is stored, against a client built
here from that token rather than from the file it is not yet in.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from etsy_listings.clients.etsy.listings import EtsyListingClient, HttpEtsyListingClient
from etsy_listings.clients.etsy.oauth import TokenResponse
from etsy_listings.clients.etsy.shops import EtsyShopClient, HttpEtsyShopClient
from etsy_listings.clients.etsy.tokens import TokenStore, utcnow
from etsy_listings.clients.etsy.transport import OAuthClient
from etsy_listings.clients.etsy.transport import Transport as EtsyTransport
from etsy_listings.clients.printify import (
    CachedCatalogClient,
    CatalogClient,
    HttpCatalogClient,
    HttpPrintifyClient,
    PrintifyClient,
    Transport,
)
from etsy_listings.config.secrets import EtsyAppKey, Secrets
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import Workspace

OAuthFactory = Callable[[str], OAuthClient]
"""How to reach Etsy's token endpoint, given a keystring. Injected only so
`auth`'s tests can drive the whole flow without a socket."""

Clock = Callable[[], datetime]


# ------------------------------------------------------------------ Printify


def printify_transport(root: Path) -> Transport:
    """One connection to Printify, with its token resolved lazily.

    Shared by both clients because it is one host and one token: they differ
    in what they are allowed to *ask*, which is a matter of which protocol the
    caller holds, not of which socket the bytes leave through (A22).
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


def catalog_client(workspace: Workspace) -> CatalogClient:
    """Blueprints, providers and variants, over the workspace's disk cache."""
    return CachedCatalogClient(
        HttpCatalogClient(printify_transport(workspace.root)), workspace.catalog_cache_dir()
    )


def printify_client(workspace: Workspace) -> PrintifyClient:
    """The shop-scoped, writing half of the Printify surface."""
    return HttpPrintifyClient(printify_transport(workspace.root))


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


def etsy_transport(root: Path) -> EtsyTransport | None:
    """A transport carrying both credentials Etsy wants: the app key on every
    request, and a bearer resolved through the store at the moment it is sent.

    ``None`` when the workspace has no key pair. A workspace that has one but
    has never signed in gets a transport that fails when it is *used* -- which
    is the right moment, since the key pair alone is enough for the unscoped
    calls `setup` and `auth` make.
    """
    app_key = etsy_app_key(root)
    if app_key is None:
        return None
    return EtsyTransport(app_key, bearer=etsy_token_store(root).access_token)


def etsy_listing_client(root: Path) -> EtsyListingClient | None:
    """The signed-in Etsy connection Phase 3's stages write through, or
    ``None`` before `auth etsy` has run."""
    transport = etsy_transport(root)
    if transport is None:
        return None
    return HttpEtsyListingClient(transport)


def etsy_shop_client(root: Path) -> EtsyShopClient | None:
    """The unscoped, read-only Etsy surface `setup` also uses (`shops.py`):
    shop/section/policy lookups that need only the app key pair, never a
    signed-in bearer -- ``None`` only when the workspace has no key pair at
    all.

    Deliberately not built from :func:`etsy_transport`: that always hands the
    transport a bearer *callable*, which every request then calls, and the
    store raises when no tokens have ever been saved -- fine for the scoped
    listing surface, which cannot do anything unsigned-in anyway, but wrong
    here. A bearer is attached only when tokens already exist, so a workspace
    with a key pair but no sign-in yet can still resolve its own shop's
    sections (a bearer is a bonus for these calls, never a requirement --
    mirrors `setupcmd.interactive._default_etsy_access`).
    """
    app_key = etsy_app_key(root)
    if app_key is None:
        return None
    tokens = etsy_token_store(root).load()
    bearer = etsy_token_store(root).access_token if tokens is not None else None
    return HttpEtsyShopClient(EtsyTransport(app_key, bearer=bearer))


# ------------------------------------------------------------------- the run


def run_context(workspace: Workspace, on_event: EventSink | None = None) -> RunContext:
    """Everything a run may need, none of it demanded up front.

    The optional clients are what let one context serve every phase: a
    workspace with no Printify shop and no Etsy sign-in still plans and still
    renders, and the stages that need a client report themselves blocked
    rather than the run failing to start (A20, A26).
    """
    sink = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=catalog_client(workspace),
        printify=printify_client(workspace),
        etsy=etsy_listing_client(workspace.root),
        **sink,
    )

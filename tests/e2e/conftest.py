"""Gating for the e2e layer: a real token, or a clean skip.

The token is read from the process environment first and from a workspace
``.env`` second, using the same :class:`Secrets` loader the CLI uses -- so a
contributor with a working ``etsy-listings`` setup can run this layer by
pointing ``ETSY_LISTINGS_ROOT`` at that workspace, with nothing new to
configure and no second place for a credential to live.

Never part of a default run: ``addopts = "-m 'not e2e'"`` in pyproject
excludes it, so these only execute under an explicit ``-m e2e``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest

from etsy_listings import connections
from etsy_listings.ai.providers import AiProvider, FakeAiProvider
from etsy_listings.clients.etsy import EtsyAuthError, HttpEtsyListingClient
from etsy_listings.clients.printify import HttpCatalogClient, PrintifyClient, Transport
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR, MissingCredentialError, Secrets
from etsy_listings.ui.api.seo import default_ai_providers
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import Workspace, layout

from tests.support.ai_runs import DRAFTED_BRIEF, QUERIES, proposal_payload
from tests.support.builders import (
    edit_garment_profile,
    edit_listing,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
    set_shop_id,
)

SHOP_ENV_VAR = "PRINTIFY_SHOP_ID"
"""Which shop the write-side tests create their throwaway product in.
Optional -- an account with a single shop needs no answer."""


@pytest.fixture(scope="session")
def etsy_market_workspace(prerequisite_missing) -> Workspace:
    """A configured Etsy key pair for read-only market calls; no sign-in is needed."""
    root = os.environ.get(layout.ROOT_ENV_VAR)
    if not root:
        prerequisite_missing(
            f"{layout.ROOT_ENV_VAR} must point at a workspace with an Etsy app key"
        )
    workspace = Workspace.discover(root_override=to_native_path(root))
    if connections.etsy_market_client(workspace.root) is None:
        prerequisite_missing(f"{root}: no Etsy app key -- run `etsy-listings auth etsy` there")
    return workspace


@pytest.fixture
def ai_providers() -> Callable[[Workspace], Sequence[AiProvider]]:
    """Fake AI in CI and by default; E2E_REAL_AI=1 uses signed-in Codex/Claude locally.

    Both choices enter through create_app's public provider factory. The fake
    supplies all three chain responses, so CI tests real Etsy research without
    depending on a developer's local AI sign-in.
    """
    if os.environ.get("E2E_REAL_AI") == "1":
        return default_ai_providers

    def fake(_workspace: Workspace) -> Sequence[AiProvider]:
        return [
            FakeAiProvider(
                name="codex",
                responses=[
                    json.dumps({"brief": DRAFTED_BRIEF}),
                    json.dumps({"queries": QUERIES}),
                    proposal_payload(),
                ],
            )
        ]

    return fake


def _token() -> str | None:
    """The Printify token, or ``None`` if this machine has not got one."""
    from_env = os.environ.get(PRINTIFY_TOKEN_VAR)
    if from_env:
        return from_env

    root = os.environ.get(layout.ROOT_ENV_VAR)
    if not root:
        return None
    env_file = to_native_path(root) / layout.ENV_FILE
    if not env_file.is_file():
        return None
    try:
        return Secrets.load(env_file).require_printify_api_token()
    except MissingCredentialError:
        return None


@pytest.fixture(scope="session")
def printify_token(prerequisite_missing) -> str:
    token = _token()
    if not token:
        prerequisite_missing(
            f"no Printify credentials: set {PRINTIFY_TOKEN_VAR}, or point "
            f"{layout.ROOT_ENV_VAR} at a workspace whose .env has it"
        )
    return token


@pytest.fixture(scope="session")
def catalog(printify_token: str) -> HttpCatalogClient:
    """One client for the whole session.

    Read-only: every call through *this* client is a GET against
    ``/v1/catalog/*``, so it creates no products and costs no state.
    ``printify_api`` below is the one that writes -- the Phase 2 product tests
    create a throwaway product in ``printify_shop`` and delete it in teardown.
    """
    return HttpCatalogClient(Transport(printify_token))


@pytest.fixture(scope="session")
def contract_fixtures() -> dict[str, object]:
    """The payload transcripts the contract layer asserts against.

    Imported from the contract test rather than duplicated, because the whole
    point of comparing them here is that there is exactly one copy: if
    Printify's real response stops matching, the file the *offline* tests
    trust is the file this layer names. (``pythonpath = ["."]`` in
    pyproject.toml is what makes ``tests.contract`` importable from here.)
    """
    from tests.contract import test_catalog_http as contract

    return {
        "blueprints": contract.BLUEPRINTS_PAYLOAD,
        "providers": contract.PROVIDERS_PAYLOAD,
        "variants": contract.VARIANTS_PAYLOAD,
    }


@pytest.fixture(scope="session")
def printify_api(printify_token: str) -> Iterator[httpx.Client]:
    """A bare authenticated client against the *shop* API.

    Deliberately not :class:`HttpCatalogClient`: that one is scoped to
    ``/v1/catalog`` and Phase 2's own client does not exist yet. The write-side
    tests below are recon -- they establish what the product endpoints require
    before anything is built on them -- so they talk to the API directly, and
    move onto ``PrintifyClient`` when there is one.
    """
    with httpx.Client(
        base_url="https://api.printify.com/v1",
        timeout=120.0,
        headers={
            "Authorization": f"Bearer {printify_token}",
            "User-Agent": "etsy-listings (e2e test)",
        },
    ) as client:
        yield client


@pytest.fixture(scope="session")
def printify_shop(printify_api: httpx.Client, prerequisite_missing) -> dict[str, Any]:
    """The shop the write-side tests create products in.

    ``PRINTIFY_SHOP_ID`` names it explicitly. Without that, an account with
    exactly one shop is unambiguous and is used; an account with several is
    not, and skips rather than guessing -- these tests write, and writing into
    the wrong shop is not a mistake worth risking to save an env var.
    """
    response = printify_api.get("/shops.json")
    response.raise_for_status()
    shops: list[dict[str, Any]] = response.json()
    if not shops:
        prerequisite_missing("the Printify account has no shops to create a product in")

    wanted = os.environ.get(SHOP_ENV_VAR)
    if wanted:
        match = next((s for s in shops if str(s["id"]) == wanted.strip()), None)
        if match is None:
            prerequisite_missing(
                f"{SHOP_ENV_VAR}={wanted} names no shop on this account; "
                f"it has {[(s['id'], s['title']) for s in shops]}"
            )
        return match

    if len(shops) > 1:
        prerequisite_missing(
            f"the account has {len(shops)} shops, so which one to write to is ambiguous: "
            f"set {SHOP_ENV_VAR} to one of {[(s['id'], s['title']) for s in shops]}"
        )
    return shops[0]


# ---------------------------------------------- the throwaway shops (Phase 3)

PrerequisiteMissing = Callable[[str], NoReturn]


@pytest.fixture(scope="session")
def credentials_workspace(prerequisite_missing: PrerequisiteMissing) -> Workspace:
    """The already-set-up workspace named by ``ETSY_LISTINGS_ROOT`` -- the
    source of the shop ids and the Etsy sign-in the write-side tests borrow
    rather than fabricate. Distinct from each test's own workspace, which is
    a fresh copy of the fixture that the test renders and applies into.
    """
    root = os.environ.get(layout.ROOT_ENV_VAR)
    if not root:
        prerequisite_missing(
            f"{layout.ROOT_ENV_VAR} must point at a workspace that has already run "
            f"`etsy-listings setup` and `etsy-listings auth etsy`"
        )
    workspace = Workspace.discover(root_override=to_native_path(root))
    if workspace.defaults.printify.shop_id is None:
        prerequisite_missing(f"{root}: no printify.shop_id -- run `etsy-listings setup` there")
    if workspace.defaults.etsy.shop_id is None:
        prerequisite_missing(f"{root}: no etsy.shop_id -- run `etsy-listings setup` there")
    return workspace


@pytest.fixture(scope="session")
def etsy_client(
    credentials_workspace: Workspace, prerequisite_missing: PrerequisiteMissing
) -> HttpEtsyListingClient:
    """The same connection `apply` uses, assembled the same way.

    Built through ``connections`` rather than by hand: this fixture was the
    fourth copy of that five-step sequence, and the one nobody would remember
    to update -- it only runs where there are real credentials. What is left
    here is the part that is genuinely the e2e layer's, which is deciding
    what counts as a missing prerequisite.
    """
    root = credentials_workspace.root
    transport = connections.etsy_transport(root)
    if transport is None:
        prerequisite_missing(f"{root}: no Etsy app key -- run `etsy-listings auth etsy` there")
    if connections.etsy_token_store(root).load() is None:
        prerequisite_missing(
            f"{root}: no stored Etsy sign-in -- run `etsy-listings auth etsy` there"
        )
    try:
        transport.ping()
    except EtsyAuthError as exc:
        prerequisite_missing(f"Etsy app key rejected: {exc}")
    client = connections.etsy_listing_client(root)
    assert isinstance(client, HttpEtsyListingClient)
    return client


@pytest.fixture(scope="session")
def printify_client(printify_token: str) -> PrintifyClient:
    return connections.printify_client_for(printify_token)


def point_at_throwaway_shops(
    root: Path,
    credentials_workspace: Workspace,
    etsy_client: HttpEtsyListingClient,
    prerequisite_missing: PrerequisiteMissing,
) -> None:
    """Configure a fresh copy of the fixture workspace for the shops named by
    ``credentials_workspace``, so every stage of the fixture listing -- and
    of a listing template saved from it -- can run against the real APIs."""
    set_shop_id(root, credentials_workspace.defaults.printify.require_shop_id())
    etsy_shop_id = credentials_workspace.defaults.etsy.require_shop_id()
    set_etsy_shop_id(root, etsy_shop_id)
    # A shipping profile is **required** for `etsy_listing` to run at all
    # (decision 2: no listing- or shop-level name means a `Blocked`), and
    # leaving it unset is what kept that stage out of every run of the
    # Phase 3 test. Resolved from the shop rather than hard-coded, so this
    # configures itself against whichever throwaway shop it is pointed at --
    # and by name, which is also what exercises ADR-0033's name -> id resolution
    # against the real API.
    profiles = [p for p in etsy_client.shipping_profiles(etsy_shop_id) if not p.is_deleted]
    if not profiles:
        prerequisite_missing(
            f"Etsy shop {etsy_shop_id} has no shipping profile -- create one in Shop Manager; "
            f"`etsy_listing` cannot patch a listing without one (ADR-0032)"
        )
    set_etsy_listing_defaults(root, who_made="i_did", shipping_profile=profiles[0].title)
    # `i_did`, not the real `someone_else` default: this throwaway shop is not
    # guaranteed to have a production partner declared, and the point of
    # these tests is the publish/patch/media cycle, not decision 3's partner
    # ladder (covered at the unit and behaviour layers already).

    # The fixture garment profile's `XXL`/`XXXL` are the offline fakes' own
    # naming, shared with every unit and behaviour test that uses this
    # fixture -- not what the real Comfort Colors 1717 / Monster Digital
    # catalog calls them (`2XL`/`3XL`/`4XL`). Overridden here, in each test's
    # own copy only, so size resolution against the live catalog doesn't
    # raise `UnknownSizeError`; size-naming itself is already covered offline
    # and isn't this layer's job. The fixture listing's prices follow, which
    # is also what a listing template saved from it carries.
    edit_garment_profile(
        root, "comfort-colors-1717", sizes=["S", "M", "L", "XL", "2XL", "3XL", "4XL"]
    )
    edit_listing(
        root,
        prices={
            "S": "349 NOK",
            "M": "349 NOK",
            "L": "349 NOK",
            "XL": "359 NOK",
            "2XL": "369 NOK",
            "3XL": "379 NOK",
            "4XL": "379 NOK",
        },
    )

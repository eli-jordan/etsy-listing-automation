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

import os
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from etsy_listings.catalog.http import HttpCatalogClient
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR, MissingCredentialError, Secrets
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import layout

SHOP_ENV_VAR = "PRINTIFY_SHOP_ID"
"""Which shop the write-side tests create their throwaway product in.
Optional -- an account with a single shop needs no answer."""


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
    return HttpCatalogClient(printify_token)


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

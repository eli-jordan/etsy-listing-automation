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
from pathlib import Path

import pytest

from etsy_listings.catalog.http import HttpCatalogClient
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR, MissingCredentialError, Secrets
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import layout


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
def printify_token() -> str:
    token = _token()
    if not token:
        pytest.skip(
            f"no Printify credentials: set {PRINTIFY_TOKEN_VAR}, or point "
            f"{layout.ROOT_ENV_VAR} at a workspace whose .env has it"
        )
    return token


@pytest.fixture(scope="session")
def catalog(printify_token: str) -> HttpCatalogClient:
    """One client for the whole session.

    Read-only: every call in this layer is a GET against
    ``/v1/catalog/*``, so it creates no products, costs no state, and can be
    re-run as often as you like. The write-side e2e tests that genuinely do
    cost state arrive with Phase 2, against a throwaway shop.
    """
    return HttpCatalogClient(printify_token)


@pytest.fixture(scope="session")
def contract_fixtures() -> dict[str, object]:
    """The payload transcripts the contract layer asserts against.

    Imported from the contract test rather than duplicated, because the whole
    point of comparing them here is that there is exactly one copy: if
    Printify's real response stops matching, the file the *offline* tests
    trust is the file this layer names.
    """
    from tests.contract import test_catalog_http as contract

    return {
        "blueprints": contract.BLUEPRINTS_PAYLOAD,
        "providers": contract.PROVIDERS_PAYLOAD,
        "variants": contract.VARIANTS_PAYLOAD,
    }


def pytest_configure(config: pytest.Config) -> None:
    """Make ``tests`` importable so ``contract_fixtures`` can reach the
    transcripts. ``rootdir`` is on ``sys.path`` under pytest's default import
    mode, but only once a package marker exists -- this keeps that explicit."""
    root = Path(__file__).resolve().parents[2]
    if str(root) not in os.sys.path:
        os.sys.path.insert(0, str(root))

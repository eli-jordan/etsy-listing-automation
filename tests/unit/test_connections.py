"""What a workspace can talk to, and when it is asked for a credential.

The two rules this module exists to hold in one place, both of which used to
be re-decided at four call sites:

- a credential is resolved when it is *used*, never when a client is built, so
  a workspace that has only ever rendered mockups can still `plan`;
- a missing Etsy sign-in is an ordinary state (``None``), not a failure.

Two of these tests lived in ``test_unlock_command.py``, under a section header
admitting they were about something else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings import connections
from etsy_listings.clients.etsy.listings import HttpEtsyListingClient
from etsy_listings.config.secrets import MissingCredentialError
from etsy_listings.workspace import layout
from etsy_listings.workspace.workspace import Workspace

KEY_PAIR = "ETSY_KEYSTRING=test-keystring\nETSY_SHARED_SECRET=test-secret\n"


def _env(root: Path, contents: str) -> None:
    (root / layout.ENV_FILE).write_text(contents, encoding="utf-8")


# ------------------------------------------------------------------ Printify


def test_a_printify_transport_does_not_need_a_token_to_exist(workspace_root: Path) -> None:
    """The fixture workspace has no ``.env`` at all. `plan` builds a catalog
    client it may never call, so demanding a token here would fail every
    workspace that has not needed one yet (A22)."""
    workspace = Workspace.discover(root_override=workspace_root)

    assert connections.catalog_client(workspace) is not None
    assert connections.printify_client(workspace) is not None


def test_the_token_is_demanded_at_the_moment_it_is_used(workspace_root: Path) -> None:
    """And when it is missing, it is reported by name and file rather than as
    a raw 401 out of httpx."""
    transport = connections.printify_transport(workspace_root)

    with pytest.raises(MissingCredentialError):
        transport.get("/v1/shops.json")


# ---------------------------------------------------------------------- Etsy


def test_no_etsy_credentials_means_no_etsy_client(workspace_root: Path) -> None:
    """`plan`/`apply` in a workspace that has never run `auth etsy` must not be
    made to configure it just to render mockups or write to Printify -- the
    same reasoning the Printify token already gets."""
    assert connections.etsy_app_key(workspace_root) is None
    assert connections.etsy_transport(workspace_root) is None
    assert connections.etsy_listing_client(workspace_root) is None


def test_etsy_credentials_present_build_a_real_client(workspace_root: Path) -> None:
    _env(workspace_root, KEY_PAIR)

    assert isinstance(connections.etsy_listing_client(workspace_root), HttpEtsyListingClient)


def test_half_a_key_pair_reads_as_absent(workspace_root: Path) -> None:
    """`auth etsy` captures both halves in one step, so a lone keystring is an
    interrupted capture -- and the remedy is the one a blocked stage already
    names. Erroring here would fail a `plan` that only wanted to render."""
    _env(workspace_root, "ETSY_KEYSTRING=test-keystring\n")

    assert connections.etsy_app_key(workspace_root) is None
    assert connections.etsy_listing_client(workspace_root) is None


def test_the_token_store_is_the_one_in_this_workspace(workspace_root: Path) -> None:
    """Where the rotating refresh token lives is this module's answer, not
    four modules' -- ``.auth/`` beside the workspace, never the repo (A23)."""
    store = connections.etsy_token_store(workspace_root)

    assert store.path == workspace_root / layout.AUTH_DIR / layout.ETSY_TOKENS_FILE


def test_a_store_can_be_built_for_a_workspace_with_no_credentials(workspace_root: Path) -> None:
    """`auth --check` builds one to answer "what have I got?", which must not
    require having anything. The keystring is resolved inside the refresh."""
    assert connections.etsy_token_store(workspace_root).load() is None


# ------------------------------------------------------------------- the run


def test_a_run_context_carries_every_client_a_stage_might_ask_for(workspace_root: Path) -> None:
    """One context serves every phase: the stages that need a client they do
    not have report themselves blocked, rather than the run failing to start."""
    workspace = Workspace.discover(root_override=workspace_root)

    ctx = connections.run_context(workspace)

    assert ctx.workspace is workspace
    assert ctx.catalog is not None
    assert ctx.printify is not None
    assert ctx.etsy is None  # no Etsy sign-in in the fixture workspace

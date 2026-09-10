"""`unlock`: clear a Printify product stuck publishing (PRD risk 6).

Its one job -- `publishing_failed.json` actually clearing a genuine lock --
has never been observed against a real stuck publish (none has stuck in
probing), so what is tested here is the command's own plumbing: it finds the
right product id, calls the right remedy, and fails cleanly when there is
nothing to unlock.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from etsy_listings.cli import app as cli
from etsy_listings.cli.app import app
from etsy_listings.clients.etsy import HttpEtsyListingClient
from etsy_listings.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_lock, set_shop_id

runner = CliRunner()
SHOP_ID = 28819281
PRODUCT_ID = "6a9ffdbfecfdc9324d023442"


def _unlock(root: Path, *args: str):
    return runner.invoke(app, ["unlock", LISTING, *args, "--root", str(root)])


def _write_lock(root: Path, **remote: object) -> None:
    lock = a_lock(remote=remote)
    lock.write(root / "listings" / LISTING / "state.lock.json")


def test_no_lockfile_says_theres_nothing_to_unlock(workspace_root: Path) -> None:
    result = _unlock(workspace_root)

    assert result.exit_code == 1
    assert "nothing to unlock" in result.output


def test_a_lockfile_with_no_product_id_says_so(workspace_root: Path) -> None:
    _write_lock(workspace_root)

    result = _unlock(workspace_root)

    assert result.exit_code == 1
    assert "nothing to unlock" in result.output


def test_no_printify_shop_id_fails_cleanly(workspace_root: Path) -> None:
    _write_lock(workspace_root, printify_product_id=PRODUCT_ID)

    result = _unlock(workspace_root)

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "setup" in result.output


def test_it_calls_publishing_failed_on_the_right_product(workspace_root: Path, monkeypatch) -> None:
    set_shop_id(workspace_root, SHOP_ID)
    _write_lock(workspace_root, printify_product_id=PRODUCT_ID)
    fake = FakePrintifyClient()
    monkeypatch.setattr(cli, "_clients", lambda workspace: (FakeCatalogClient([], {}, {}), fake))

    result = _unlock(workspace_root)

    assert result.exit_code == 0, result.output
    assert fake.publishing_failed_calls == [PRODUCT_ID]
    assert PRODUCT_ID in result.output
    assert "apply" in result.output.lower()


# ------------------------------------------------------- RunContext.etsy wiring


def test_no_etsy_credentials_means_no_etsy_client(workspace_root: Path) -> None:
    """`plan`/`apply` in a workspace that has never run `auth etsy` must not
    be made to configure it just to render mockups or write to Printify --
    the same reasoning `_transport` already applies to Printify's token."""
    workspace = Workspace.discover(root_override=workspace_root)

    assert cli._etsy_client(workspace) is None


def test_etsy_credentials_present_build_a_real_client(workspace_root: Path) -> None:
    (workspace_root / ".env").write_text(
        "ETSY_KEYSTRING=test-keystring\nETSY_SHARED_SECRET=test-secret\n", encoding="utf-8"
    )
    workspace = Workspace.discover(root_override=workspace_root)

    client = cli._etsy_client(workspace)

    assert isinstance(client, HttpEtsyListingClient)

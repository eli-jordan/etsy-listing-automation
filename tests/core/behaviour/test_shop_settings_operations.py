"""The Admin page's Shop operations, called directly against real files.

Admin plan, PR 3: ``shop.yaml`` reads with a revision of its exact bytes,
revision-checked edits validated as a whole ``Defaults`` document, no-op
edits that leave the file byte-identical, connection rows, and live lookups
that fail without losing the saved choice. Etsy and Printify are fakes.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core import connections
from etsy_listings.core.application import shop_settings
from etsy_listings.core.application.refusals import InvalidShopEdit, ShopRevisionConflict
from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient, FakeEtsyShopClient
from etsy_listings.core.clients.etsy.models import (
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
)
from etsy_listings.core.clients.etsy.models import Shop as EtsyShop
from etsy_listings.core.clients.etsy.tokens import StoredTokens
from etsy_listings.core.clients.etsy.transport import EtsyApiError
from etsy_listings.core.clients.printify import FakeCatalogClient, PrintProvider
from etsy_listings.core.clients.printify.fakes import FakePrintifyClient
from etsy_listings.core.clients.printify.models import Shop as PrintifyShop
from etsy_listings.core.config.secrets import (
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
)
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import set_etsy_shop_id, set_shop_id

SHOP_YAML = """\
# The seller's own notes, kept by every edit.
printify:
  shop_name: TakeAHikeTees   # checked against Printify
  shop_id: 28819281
  preferred_print_provider: Monster Digital
etsy:
  shop_name: TakeAHikeTees
  shop_id: 51007712
  currency: NOK   # the shop sells in kroner
  listing_defaults:
    who_made: i_did
    when_made: made_to_order
    is_supply: false
    renewal: manual
    shipping_profile: Printify standard
"""


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    (workspace_root / layout.SHOP_FILE).write_bytes(SHOP_YAML.replace("\n", "\r\n").encode())
    return Workspace.discover(root_override=workspace_root)


def shop_bytes(workspace: Workspace) -> bytes:
    return (workspace.root / layout.SHOP_FILE).read_bytes()


def tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ------------------------------------------------------------------ reading


def test_a_read_carries_the_exact_file_revision_and_its_values(workspace: Workspace) -> None:
    view = shop_settings.read_shop(workspace)

    assert view.revision == hashlib.sha256(shop_bytes(workspace)).hexdigest()
    assert view.defaults.etsy.currency == "NOK"
    assert view.defaults.etsy.listing_defaults.shipping_profile == "Printify standard"


# ------------------------------------------------------------------ editing


def test_an_edit_changes_only_its_value_and_keeps_the_sellers_text(workspace: Workspace) -> None:
    before = shop_settings.read_shop(workspace)

    after = shop_settings.edit_shop(
        workspace,
        expected_revision=before.revision,
        changes={"etsy.listing_defaults.renewal": "auto"},
    )

    expected = SHOP_YAML.replace("renewal: manual", "renewal: auto").replace("\n", "\r\n")
    assert shop_bytes(workspace) == expected.encode()
    assert after.revision == hashlib.sha256(expected.encode()).hexdigest()
    assert after.defaults.etsy.listing_defaults.renewal == "auto"
    # The running server reads the new defaults without a restart.
    assert workspace.defaults.etsy.listing_defaults.renewal == "auto"


def test_print_on_demand_writes_its_three_values_in_one_save(workspace: Workspace) -> None:
    revision = shop_settings.read_shop(workspace).revision

    after = shop_settings.edit_shop(
        workspace, expected_revision=revision, changes=shop_settings.PRINT_ON_DEMAND
    )

    defaults = after.defaults.etsy.listing_defaults
    assert (defaults.who_made, defaults.when_made, defaults.is_supply) == (
        "someone_else",
        "made_to_order",
        False,
    )
    assert b"who_made: someone_else\r\n" in shop_bytes(workspace)


def test_a_return_policy_is_saved_by_its_terms(workspace: Workspace) -> None:
    revision = shop_settings.read_shop(workspace).revision
    terms = {"accepts_returns": False, "accepts_exchanges": True, "within_days": 30}

    shop_settings.edit_shop(
        workspace,
        expected_revision=revision,
        changes={"etsy.listing_defaults.return_policy": terms},
    )

    policy = Workspace.discover(root_override=workspace.root).defaults.etsy.listing_defaults
    assert policy.return_policy is not None
    assert policy.return_policy.model_dump() == terms


def test_a_save_against_a_stale_revision_never_overwrites(workspace: Workspace) -> None:
    revision = shop_settings.read_shop(workspace).revision
    edited = shop_bytes(workspace) + b"# added in an editor\r\n"
    (workspace.root / layout.SHOP_FILE).write_bytes(edited)

    with pytest.raises(ShopRevisionConflict):
        shop_settings.edit_shop(
            workspace, expected_revision=revision, changes={"etsy.currency": "EUR"}
        )

    assert shop_bytes(workspace) == edited
    assert workspace.defaults.etsy.currency == "NOK"


def test_an_invalid_value_is_refused_with_its_field_and_never_written(
    workspace: Workspace,
) -> None:
    original = shop_bytes(workspace)
    revision = shop_settings.read_shop(workspace).revision

    with pytest.raises(InvalidShopEdit) as refused:
        shop_settings.edit_shop(
            workspace,
            expected_revision=revision,
            changes={"etsy.listing_defaults.renewal": "weekly"},
        )

    assert set(refused.value.field_errors) == {"etsy.listing_defaults.renewal"}
    assert shop_bytes(workspace) == original


def test_a_currency_etsy_payments_does_not_support_is_refused(workspace: Workspace) -> None:
    revision = shop_settings.read_shop(workspace).revision

    with pytest.raises(InvalidShopEdit) as refused:
        shop_settings.edit_shop(
            workspace, expected_revision=revision, changes={"etsy.currency": "JPY"}
        )

    assert set(refused.value.field_errors) == {"etsy.currency"}


def test_a_currency_minor_units_cannot_carry_is_refused(workspace: Workspace) -> None:
    """VND has no minor unit, and ADR-0019's minor units assume two."""
    revision = shop_settings.read_shop(workspace).revision

    with pytest.raises(InvalidShopEdit) as refused:
        shop_settings.edit_shop(
            workspace, expected_revision=revision, changes={"etsy.currency": "VND"}
        )

    assert set(refused.value.field_errors) == {"etsy.currency"}


def test_a_key_the_page_does_not_edit_is_refused(workspace: Workspace) -> None:
    revision = shop_settings.read_shop(workspace).revision

    with pytest.raises(InvalidShopEdit) as refused:
        shop_settings.edit_shop(workspace, expected_revision=revision, changes={"etsy.shop_id": 1})

    assert set(refused.value.field_errors) == {"etsy.shop_id"}


def test_saving_the_value_already_there_leaves_the_file_byte_identical(
    workspace: Workspace,
) -> None:
    path = workspace.root / layout.SHOP_FILE
    original = path.read_bytes()
    stamp = path.stat().st_mtime_ns
    revision = shop_settings.read_shop(workspace).revision

    after = shop_settings.edit_shop(
        workspace,
        expected_revision=revision,
        changes={"etsy.currency": "NOK", "etsy.listing_defaults.is_supply": False},
    )

    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == stamp
    assert after.revision == revision


def test_a_cleared_optional_default_is_removed(workspace: Workspace) -> None:
    revision = shop_settings.read_shop(workspace).revision

    after = shop_settings.edit_shop(
        workspace,
        expected_revision=revision,
        changes={"etsy.listing_defaults.shipping_profile": None},
    )

    assert after.defaults.etsy.listing_defaults.shipping_profile is None
    assert b"shipping_profile" not in shop_bytes(workspace)


def test_defaults_and_currency_edits_leave_every_listing_file_alone(
    workspace: Workspace,
) -> None:
    """Shop defaults are inherited when a listing is planned; an edit copies
    nothing into existing listing files, lockfiles or prices (ADR-0006,
    ADR-0019: a saved explicit price keeps its currency)."""
    listings = workspace.root / layout.LISTINGS_DIR
    before = tree_digest(listings)
    assert before, "the fixture workspace has listings to protect"
    revision = shop_settings.read_shop(workspace).revision

    shop_settings.edit_shop(
        workspace,
        expected_revision=revision,
        changes={
            "etsy.currency": "EUR",
            **shop_settings.PRINT_ON_DEMAND,
            "etsy.listing_defaults.shipping_profile": "Printify express",
            "printify.preferred_print_provider": "SwiftPOD",
        },
    )

    assert tree_digest(listings) == before


# ------------------------------------------------------------------ lookups


def etsy_lists(**overrides: object) -> FakeEtsyListingClient:
    return FakeEtsyListingClient(
        shipping_profiles=[
            ShippingProfile(shipping_profile_id=1, title="Printify express"),
            ShippingProfile(shipping_profile_id=2, title="Retired", is_deleted=True),
        ],
        production_partners=[
            ProductionPartner(production_partner_id=7, partner_name="Printify", location="US")
        ],
        policies=[
            ReturnPolicy(
                return_policy_id=3,
                accepts_returns=False,
                accepts_exchanges=True,
                return_deadline=30,
            )
        ],
    )


CATALOG = FakeCatalogClient(
    [],
    {},
    {},
    all_providers=[
        PrintProvider(id=3, title="SwiftPOD"),
        PrintProvider(id=29, title="Monster Digital"),
    ],
)


class FailingEtsy(FakeEtsyListingClient):
    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]:
        raise EtsyApiError(503, error="Etsy is down")


class FailingCatalog(FakeCatalogClient):
    def all_print_providers(self) -> list[PrintProvider]:
        raise EtsyApiError(503, error="Printify is down")


def test_lookups_offer_the_shops_lists_with_the_preferred_provider_first(
    workspace: Workspace,
) -> None:
    lookups = shop_settings.shop_lookups(workspace, etsy=etsy_lists(), catalog=CATALOG)

    assert lookups.etsy.available
    assert lookups.etsy.shipping_profiles == ("Printify express",)
    assert lookups.etsy.production_partners == ("Printify",)
    (policy,) = lookups.etsy.return_policies
    assert policy.terms == {"accepts_returns": False, "accepts_exchanges": True, "within_days": 30}
    assert policy.label == "exchanges within 30 days"
    assert lookups.printify.available
    assert lookups.printify.print_providers == ("Monster Digital", "SwiftPOD")


def test_an_etsy_lookup_failure_leaves_the_printify_list_and_writes_nothing(
    workspace: Workspace,
) -> None:
    original = shop_bytes(workspace)

    lookups = shop_settings.shop_lookups(workspace, etsy=FailingEtsy(), catalog=CATALOG)

    assert not lookups.etsy.available
    assert lookups.etsy.problem is not None and "Etsy is down" in lookups.etsy.problem
    assert lookups.etsy.shipping_profiles == ()
    assert lookups.printify.available
    assert shop_bytes(workspace) == original
    assert workspace.defaults.etsy.listing_defaults.shipping_profile == "Printify standard"


def test_a_printify_lookup_failure_leaves_the_etsy_lists(workspace: Workspace) -> None:
    failing = FailingCatalog([], {}, {})

    lookups = shop_settings.shop_lookups(workspace, etsy=etsy_lists(), catalog=failing)

    assert lookups.etsy.available
    assert not lookups.printify.available
    assert lookups.printify.problem is not None


def test_etsy_lists_wait_for_a_configured_shop(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    etsy = etsy_lists()

    lookups = shop_settings.shop_lookups(workspace, etsy=etsy, catalog=CATALOG)

    assert not lookups.etsy.available
    assert lookups.etsy.problem is not None and "etsy-listings setup" in lookups.etsy.problem
    assert etsy.shipping_profile_calls == 0


# -------------------------------------------------------------- connections


def sign_in(root: Path, *, user_id: int = 81120455) -> None:
    (root / layout.ENV_FILE).write_text(
        f"{PRINTIFY_TOKEN_VAR}=token\n{ETSY_KEYSTRING_VAR}=key\n{ETSY_SHARED_SECRET_VAR}=secret\n",
        encoding="utf-8",
    )
    now = datetime.now(UTC)
    connections.etsy_token_store(root).save(
        StoredTokens(
            access_token="a",
            refresh_token="r",
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=90),
            scope="shops_r",
            user_id=user_id,
        )
    )


ETSY_SHOP = EtsyShop(
    shop_id=51007712, shop_name="TakeAHikeTees", user_id=81120455, currency_code="NOK"
)
PRINTIFY_SHOP = PrintifyShop(id=28819281, title="TakeAHikeTees", sales_channel="etsy")


def test_a_workspace_with_nothing_connected_says_what_to_run(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)

    rows = shop_settings.shop_connections(
        workspace, etsy=FakeEtsyShopClient(), printify=FakePrintifyClient()
    )

    assert rows.etsy.state == "not_connected"
    assert rows.etsy.commands == ("etsy-listings auth etsy", "etsy-listings setup")
    assert rows.printify.state == "not_connected"
    assert rows.printify.commands == ("etsy-listings auth printify", "etsy-listings setup")


def test_signed_in_without_shop_ids_asks_only_for_setup(workspace_root: Path) -> None:
    sign_in(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)

    rows = shop_settings.shop_connections(
        workspace, etsy=FakeEtsyShopClient(), printify=FakePrintifyClient()
    )

    assert rows.etsy.commands == ("etsy-listings setup",)
    assert rows.printify.commands == ("etsy-listings setup",)


def test_connected_shops_show_their_configured_identity(workspace_root: Path) -> None:
    set_shop_id(set_etsy_shop_id(workspace_root, 51007712), 28819281)
    sign_in(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)

    rows = shop_settings.shop_connections(
        workspace,
        etsy=FakeEtsyShopClient(owned=ETSY_SHOP),
        printify=FakePrintifyClient([PRINTIFY_SHOP]),
    )

    assert (rows.etsy.state, rows.etsy.shop_name, rows.etsy.shop_id) == (
        "connected",
        "TakeAHikeTees",
        51007712,
    )
    assert rows.etsy.signed_in_user_id == 81120455
    assert rows.etsy.shop_currency == "NOK"
    assert rows.printify.state == "connected"
    assert rows.printify.shop_id == 28819281
    assert rows.printify.sales_channel == "etsy"


def test_a_failed_lookup_keeps_the_configured_identity(workspace_root: Path) -> None:
    set_shop_id(set_etsy_shop_id(workspace_root, 51007712), 28819281)
    sign_in(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)

    class Unreachable(FakeEtsyShopClient):
        def shop_by_owner(self, user_id: int) -> EtsyShop | None:
            raise EtsyApiError(503, error="Etsy is down")

    rows = shop_settings.shop_connections(
        workspace, etsy=Unreachable(), printify=FakePrintifyClient(auth_fails=True)
    )

    assert rows.etsy.state == "lookup_failed"
    assert (rows.etsy.shop_name, rows.etsy.shop_id) == ("TakeAHikeTees", 51007712)
    assert rows.etsy.problem is not None
    assert rows.printify.state == "lookup_failed"
    assert rows.printify.shop_id == 28819281


def test_a_printify_shop_the_token_cannot_see_is_a_lookup_problem(workspace_root: Path) -> None:
    set_shop_id(set_etsy_shop_id(workspace_root, 51007712), 28819281)
    sign_in(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)

    rows = shop_settings.shop_connections(
        workspace,
        etsy=FakeEtsyShopClient(owned=ETSY_SHOP),
        printify=FakePrintifyClient([PrintifyShop(id=1, title="Other")]),
    )

    assert rows.printify.state == "lookup_failed"
    assert rows.printify.problem is not None and "28819281" in rows.printify.problem

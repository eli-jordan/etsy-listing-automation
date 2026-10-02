"""Workspace configuration and shop discovery, called directly.

What ``setup`` does that is not asking: seeding the packaged prompts, reading
and writing ``shop.yaml`` and the token behind it, and finding the shops a
workspace publishes to. No Typer, no prompt -- the Etsy side is a
:class:`FakeEtsyShopClient` (module-structure plan, PR 10). The wizard's
sequencing, defaults and cancellation are ``test_setup_command.py``'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.core.ai.prompt import default_seo_prompt_text
from etsy_listings.core.application import shop_discovery, workspace_setup
from etsy_listings.core.clients.etsy.fakes import FakeEtsyShopClient
from etsy_listings.core.clients.etsy.models import ReturnPolicy
from etsy_listings.core.clients.etsy.models import Shop as EtsyShop
from etsy_listings.core.clients.printify.models import Shop
from etsy_listings.core.config.secrets import (
    ETSY_KEYSTRING_VAR,
    ETSY_SHARED_SECRET_VAR,
    PRINTIFY_TOKEN_VAR,
)
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

ANSWERS = workspace_setup.SetupAnswers(
    printify_shop_id=28819281,
    printify_shop_name="TakeAHikeTees",
    preferred_print_provider=None,
    currency="NOK",
    **workspace_setup.POD_DEFAULTS,
)

CONNECTED = Shop(id=1, title="TakeAHikeTees", sales_channel="etsy")
DISCONNECTED = Shop(id=1, title="My new store", sales_channel="disconnected")
ETSY_SHOP = EtsyShop(shop_id=12345678, shop_name="TakeAHikeTees", currency_code="USD")


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (PRINTIFY_TOKEN_VAR, ETSY_KEYSTRING_VAR, ETSY_SHARED_SECRET_VAR):
        monkeypatch.delenv(variable, raising=False)


# ------------------------------------------------------------ packaged prompts


def test_packaged_prompts_are_seeded_into_a_fresh_workspace(tmp_path: Path) -> None:
    outcomes = workspace_setup.sync_packaged_prompts(tmp_path, replace=False)

    assert {o.outcome for o in outcomes} == {"created"}
    assert [o.where for o in outcomes] == [
        f"{layout.PROMPTS_DIR}/{name}" for name, _, _ in workspace_setup.PACKAGED_PROMPTS
    ]
    seo = tmp_path / layout.PROMPTS_DIR / layout.SEO_PROMPT_FILE
    assert seo.read_text(encoding="utf-8") == default_seo_prompt_text()


def test_an_edited_prompt_is_kept_unless_replacing(tmp_path: Path) -> None:
    """ADR-0044: a seller's prompt survives every re-run but the opted-in one."""
    workspace_setup.sync_packaged_prompts(tmp_path, replace=False)
    seo = tmp_path / layout.PROMPTS_DIR / layout.SEO_PROMPT_FILE
    seo.write_text("mine", encoding="utf-8")

    kept = workspace_setup.sync_packaged_prompts(tmp_path, replace=False)
    assert kept[0].outcome == "differs"
    assert seo.read_text(encoding="utf-8") == "mine"

    replaced = workspace_setup.sync_packaged_prompts(tmp_path, replace=True)
    assert replaced[0].outcome == "replaced"
    assert replaced[0].backup == f"{layout.PROMPTS_DIR}/{layout.SEO_PROMPT_FILE}.bak"
    assert seo.read_text(encoding="utf-8") == default_seo_prompt_text()
    assert (tmp_path / replaced[0].backup).read_text(encoding="utf-8") == "mine"
    assert {o.outcome for o in replaced[1:]} == {"current"}


# ------------------------------------------------------------------ shop.yaml


def test_there_is_no_shop_document_before_setup_writes_one(tmp_path: Path) -> None:
    assert workspace_setup.read_shop_document(tmp_path) is None


def test_an_invalid_shop_document_is_still_read_so_setup_can_repair_it(tmp_path: Path) -> None:
    (tmp_path / layout.SHOP_FILE).write_text("etsy: {currency: 12}\n", encoding="utf-8")

    assert workspace_setup.read_shop_document(tmp_path) == {"etsy": {"currency": 12}}


def test_saving_writes_the_token_and_a_shop_yaml_the_workspace_reads(tmp_path: Path) -> None:
    workspace_setup.save_setup(tmp_path, printify_token="tok", answers=ANSWERS, existing=None)

    env = (tmp_path / layout.ENV_FILE).read_text(encoding="utf-8")
    assert f"{PRINTIFY_TOKEN_VAR}=tok" in env
    workspace = Workspace.discover(root_override=tmp_path)
    assert workspace.defaults.printify.require_shop_id() == 28819281
    assert workspace.defaults.etsy.currency == "NOK"


def test_saving_keeps_what_setup_never_asked_about(tmp_path: Path) -> None:
    existing = {"etsy": {"shop_id": 7, "listing_defaults": {"materials": ["cotton"]}}}

    workspace_setup.save_setup(tmp_path, printify_token="tok", answers=ANSWERS, existing=existing)

    written = yaml.safe_load((tmp_path / layout.SHOP_FILE).read_text(encoding="utf-8"))
    assert written["etsy"]["shop_id"] == 7
    assert written["etsy"]["listing_defaults"]["materials"] == ["cotton"]


# ------------------------------------------------------------- shop discovery


def test_no_stored_app_key_means_no_etsy_access(tmp_path: Path) -> None:
    assert shop_discovery.etsy_access(tmp_path) is None


def test_a_stored_app_key_gives_access_even_before_anyone_signs_in(tmp_path: Path) -> None:
    (tmp_path / layout.ENV_FILE).write_text(
        f"{ETSY_KEYSTRING_VAR}=k\n{ETSY_SHARED_SECRET_VAR}=s\n", encoding="utf-8"
    )

    access = shop_discovery.etsy_access(tmp_path)

    assert access is not None
    assert access.user_id is None


def test_a_connected_printify_shop_names_its_etsy_shop() -> None:
    client = FakeEtsyShopClient([ETSY_SHOP])

    found = shop_discovery.find_etsy_shop(shop_discovery.EtsyAccess(client, 99), CONNECTED)

    assert found == shop_discovery.FoundShop(ETSY_SHOP, "connected")
    assert client.owner_lookups == []


def test_the_signed_in_owner_is_the_next_route() -> None:
    client = FakeEtsyShopClient(owned=ETSY_SHOP)

    found = shop_discovery.find_etsy_shop(shop_discovery.EtsyAccess(client, 99), DISCONNECTED)

    assert found == shop_discovery.FoundShop(ETSY_SHOP, "owner")
    assert client.owner_lookups == [99]


def test_with_no_route_left_the_shop_is_not_found() -> None:
    client = FakeEtsyShopClient(owned=ETSY_SHOP)

    found = shop_discovery.find_etsy_shop(shop_discovery.EtsyAccess(client, None), DISCONNECTED)

    assert found is None
    assert client.owner_lookups == []


def test_a_typed_name_resolves_to_its_one_exact_match() -> None:
    client = FakeEtsyShopClient([ETSY_SHOP])

    lookup = shop_discovery.lookup_etsy_shop(client, "takeahiketees")

    assert lookup.exact == ETSY_SHOP


def test_an_unknown_name_resolves_to_nothing() -> None:
    lookup = shop_discovery.lookup_etsy_shop(FakeEtsyShopClient(), "Nobody")

    assert lookup.exact is None
    assert lookup.candidates == ()


POLICY_A = ReturnPolicy(
    return_policy_id=1, accepts_returns=True, accepts_exchanges=False, return_deadline=30
)
POLICY_B = ReturnPolicy(
    return_policy_id=2, accepts_returns=False, accepts_exchanges=True, return_deadline=14
)


def test_return_policies_put_the_current_one_first() -> None:
    client = FakeEtsyShopClient(policies=[POLICY_A, POLICY_B])
    current = shop_discovery.policy_terms(POLICY_B)

    options = shop_discovery.return_policy_options(client, ETSY_SHOP, current)

    assert options.policies == (POLICY_B, POLICY_A)
    assert options.is_current(POLICY_B)
    assert not options.is_current(POLICY_A)


def test_a_return_policy_is_addressed_by_its_terms() -> None:
    assert shop_discovery.policy_terms(POLICY_A) == {
        "accepts_returns": True,
        "accepts_exchanges": False,
        "within_days": 30,
    }


def test_the_etsy_shop_currency_wins_over_the_file_then_nok() -> None:
    assert shop_discovery.currency_default(ETSY_SHOP, {"currency": "EUR"}) == "USD"
    assert shop_discovery.currency_default(None, {"currency": "EUR"}) == "EUR"
    assert shop_discovery.currency_default(None, {}) == "NOK"

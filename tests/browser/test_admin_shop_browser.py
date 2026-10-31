"""Admin Shop autosave through the built SPA, real API and fixture shop.yaml.

Admin audit Q1 and Q2: what reaches ``shop.yaml`` when an older save's
answer arrives after a newer choice, and when one field's save fails while
a sibling's succeeds. Each test asserts the file the page wrote, not only
what the page shows.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient, FakeEtsyShopClient
from etsy_listings.core.clients.etsy.models import ShippingProfile
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.workspace import layout

from tests.support.builders import set_etsy_shop_id

pytestmark = pytest.mark.browser


@pytest.fixture
def expect(browser_type):  # noqa: ANN001, ANN201 - optional Playwright after prerequisite check
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect


@pytest.fixture(autouse=True)
def fake_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connections, "etsy_shop_client", lambda root: FakeEtsyShopClient())
    monkeypatch.setattr(connections, "etsy_listing_client", lambda root: FakeEtsyListingClient())
    monkeypatch.setattr(connections, "printify_client", lambda workspace: FakePrintifyClient())
    monkeypatch.setattr(
        connections, "catalog_client", lambda workspace: FakeCatalogClient([], {}, {})
    )


@pytest.fixture(params=["light", "dark"])
def theme(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def capture(page, theme: str, state: str) -> None:  # noqa: ANN001
    if directory := os.environ.get("ADMIN_SHOP_SCREENSHOT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"shop-{state}-{theme}.png"))


def open_defaults(page, base: str, theme: str) -> None:  # noqa: ANN001
    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme=theme)
    page.goto(f"{base}/admin")
    page.get_by_role("link", name="Listing defaults").click()


def is_save(response) -> bool:  # noqa: ANN001
    return response.url.endswith("/api/admin/shop") and response.request.method == "PATCH"


def choose(select, value: str) -> None:  # noqa: ANN001
    """What a seller does: focus the selector, pick, and leave it."""
    select.focus()
    select.select_option(value)
    select.blur()


def on_disk(root: Path) -> Defaults:
    return Defaults.load(root / layout.SHOP_FILE)


def test_a_newer_queued_choice_survives_the_older_answer(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    open_defaults(page, calibrator_server, theme)
    renewal = page.get_by_role("combobox", name="Renewal")
    expect(renewal).to_have_value("manual")
    held = []

    def hold_first(route) -> None:  # noqa: ANN001
        if route.request.method == "PATCH" and not held:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/admin/shop", hold_first)
    choose(renewal, "auto")
    expect(page.locator(".page-head__actions [role=status]")).to_contain_text("Saving")
    choose(renewal, "manual")
    first = held[0].fetch()
    with page.expect_response(
        lambda r: is_save(r) and r.request.post_data_json["changes"] == {"renewal": "manual"}
    ):
        held[0].fulfill(response=first)
        expect(renewal).to_have_value("manual")
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    expect(renewal).to_have_value("manual")
    assert on_disk(workspace_root).etsy.listing_defaults.renewal == "manual"
    capture(page, theme, "rapid")


def test_a_failed_field_stays_unsaved_through_a_sibling_success_until_retried(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    open_defaults(page, calibrator_server, theme)
    renewal = page.get_by_role("combobox", name="Renewal")
    expect(renewal).to_have_value("manual")
    capture(page, theme, "default")

    def fail_renewal(route) -> None:  # noqa: ANN001
        if route.request.method == "PATCH" and "renewal" in route.request.post_data_json["changes"]:
            route.fulfill(
                status=503, content_type="application/json", body='{"detail":"disk unavailable"}'
            )
        else:
            route.continue_()

    page.route("**/api/admin/shop", fail_renewal)
    choose(renewal, "auto")
    retry = page.get_by_role("button", name="Retry save")
    expect(retry).to_be_visible()

    who = page.get_by_role("combobox", name="Who made it")
    with page.expect_response(is_save):
        choose(who, "collective")
    assert on_disk(workspace_root).etsy.listing_defaults.who_made == "collective"
    assert on_disk(workspace_root).etsy.listing_defaults.renewal == "manual"
    expect(retry).to_be_visible()
    expect(page.get_by_text("Saved", exact=True)).to_have_count(0)
    expect(renewal).to_have_value("auto")
    capture(page, theme, "failed")

    page.unroute("**/api/admin/shop", fail_renewal)
    with page.expect_response(is_save) as retried:
        retry.click()
    assert retried.value.request.post_data_json["changes"] == {"renewal": "auto"}
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    expect(retry).to_have_count(0)
    assert on_disk(workspace_root).etsy.listing_defaults.renewal == "auto"
    assert on_disk(workspace_root).etsy.listing_defaults.who_made == "collective"
    capture(page, theme, "retried")


def test_a_choice_made_while_retry_is_pending_reaches_the_file(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    """The retry carries auto; choosing manual meanwhile is a change from
    what the file will hold, so it is saved after the retry lands."""
    open_defaults(page, calibrator_server, theme)
    renewal = page.get_by_role("combobox", name="Renewal")
    expect(renewal).to_have_value("manual")
    attempts: list[dict[str, object]] = []
    held = []

    def fail_then_hold(route) -> None:  # noqa: ANN001
        if route.request.method != "PATCH":
            route.continue_()
            return
        attempts.append(route.request.post_data_json["changes"])
        if len(attempts) == 1:
            route.fulfill(
                status=503, content_type="application/json", body='{"detail":"disk unavailable"}'
            )
        elif len(attempts) == 2:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/admin/shop", fail_then_hold)
    choose(renewal, "auto")
    retry = page.get_by_role("button", name="Retry save")
    expect(retry).to_be_visible()
    retry.click()
    expect(page.locator(".page-head__actions [role=status]")).to_contain_text("Saving")
    choose(renewal, "manual")
    assert len(attempts) == 2
    with page.expect_response(lambda r: is_save(r) and len(attempts) == 3):
        held[0].continue_()
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    assert attempts == [{"renewal": "auto"}, {"renewal": "auto"}, {"renewal": "manual"}]
    assert on_disk(workspace_root).etsy.listing_defaults.renewal == "manual"
    expect(renewal).to_have_value("manual")


@pytest.fixture
def etsy_shop(workspace_root: Path) -> None:
    """Opts the fixture into Etsy lookups. A test requests it before ``page``,
    whose server reads ``shop.yaml`` once at startup."""
    set_etsy_shop_id(workspace_root, 51007712)


def test_use_it_replaces_a_failed_draft_with_what_it_wrote(
    etsy_shop: None,
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titles = ["Printify US standard", "Printify EU standard"]
    monkeypatch.setattr(
        connections,
        "etsy_listing_client",
        lambda root: FakeEtsyListingClient(
            shipping_profiles=[
                ShippingProfile(shipping_profile_id=n, title=t) for n, t in enumerate(titles)
            ]
        ),
    )
    open_defaults(page, calibrator_server, theme)
    shipping = page.get_by_role("combobox", name="Shipping profile")
    expect(shipping).to_be_enabled()
    attempts: list[dict[str, object]] = []

    def fail_first(route) -> None:  # noqa: ANN001
        if route.request.method != "PATCH":
            route.continue_()
            return
        attempts.append(route.request.post_data_json["changes"])
        if len(attempts) == 1:
            route.fulfill(
                status=503, content_type="application/json", body='{"detail":"disk unavailable"}'
            )
        else:
            route.continue_()

    page.route("**/api/admin/shop", fail_first)
    choose(shipping, "Printify EU standard")
    expect(page.get_by_role("button", name="Retry save")).to_be_visible()

    titles.append("Printify UK standard")
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    with page.expect_response(is_save):
        page.get_by_role("button", name="Use it").click()
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    expect(shipping).to_have_value("Printify UK standard")
    assert on_disk(workspace_root).etsy.listing_defaults.shipping_profile == "Printify UK standard"

    shipping.focus()
    shipping.blur()
    page.get_by_role("combobox", name="Renewal").focus()
    expect(page.get_by_role("button", name="Retry save")).to_have_count(0)
    assert attempts == [
        {"shipping_profile": "Printify EU standard"},
        {"shipping_profile": "Printify UK standard"},
    ]
    assert on_disk(workspace_root).etsy.listing_defaults.shipping_profile == "Printify UK standard"

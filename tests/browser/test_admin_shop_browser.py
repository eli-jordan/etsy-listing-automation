"""Admin Shop autosave through the built SPA, real API and fixture shop.yaml.

Wiring only: a choice and a Retry made on the page reach ``shop.yaml``, and
Use it writes what Etsy's refreshed lookups newly offer. Each test asserts
the file the page wrote, not only what the page shows. The save queue's
ordering and failure rules (admin audit Q1 and Q2) are Vitest's:
``useSaveQueue.test.ts`` and ``AdminPage.test.tsx``. Revisions and conflicts
are ``tests/server/behaviour/test_shop_api.py``'s.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.core.clients.etsy.models import ShippingProfile
from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.workspace import layout

from tests.support.builders import set_etsy_shop_id
from tests.support.clients import FakeClients

pytestmark = pytest.mark.browser


@pytest.fixture
def expect(browser_type):
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect


@pytest.fixture
def app_options(fake_clients: FakeClients) -> dict[str, Any]:
    """Serve the app with in-memory Etsy and Printify clients."""
    return {"clients": fake_clients.factories()}


def capture(page, theme: str, state: str) -> None:
    if directory := os.environ.get("ADMIN_SHOP_SCREENSHOT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"shop-{state}-{theme}.png"))


def open_defaults(page, base: str, theme: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme=theme)
    page.goto(f"{base}/admin")
    page.get_by_role("link", name="Listing defaults").click()


def is_save(response) -> bool:
    return response.url.endswith("/api/admin/shop") and response.request.method == "PATCH"


def choose(select, value: str) -> None:
    """What a seller does: focus the selector, pick, and leave it."""
    select.focus()
    select.select_option(value)
    select.blur()


def on_disk(root: Path) -> Defaults:
    return Defaults.load(root / layout.SHOP_FILE)


def fail_every_save(route) -> None:
    if route.request.method == "PATCH":
        route.fulfill(
            status=503, content_type="application/json", body='{"detail":"disk unavailable"}'
        )
    else:
        route.continue_()


def test_a_choice_and_a_retried_failure_reach_shop_yaml(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
) -> None:
    open_defaults(page, calibrator_server, theme)
    renewal = page.get_by_role("combobox", name="Renewal")
    expect(renewal).to_have_value("manual")
    capture(page, theme, "default")

    with page.expect_response(is_save):
        choose(page.get_by_role("combobox", name="Who made it"), "collective")
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    assert on_disk(workspace_root).etsy.listing_defaults.who_made == "collective"

    page.route("**/api/admin/shop", fail_every_save)
    choose(renewal, "auto")
    retry = page.get_by_role("button", name="Retry save")
    expect(retry).to_be_visible()
    assert on_disk(workspace_root).etsy.listing_defaults.renewal == "manual"
    capture(page, theme, "failed")

    page.unroute("**/api/admin/shop", fail_every_save)
    with page.expect_response(is_save) as retried:
        retry.click()
    assert retried.value.request.post_data_json["changes"] == {"renewal": "auto"}
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    expect(retry).to_have_count(0)
    defaults = on_disk(workspace_root).etsy.listing_defaults
    assert (defaults.renewal, defaults.who_made) == ("auto", "collective")
    capture(page, theme, "retried")


@pytest.fixture
def etsy_shop(workspace_root: Path) -> None:
    """Opts the fixture into Etsy lookups. A test requests it before ``page``,
    whose server reads ``shop.yaml`` once at startup."""
    set_etsy_shop_id(workspace_root, 51007712)


def test_use_it_writes_the_profile_a_lookup_refresh_newly_offers(
    *,
    etsy_shop: None,
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
    fake_clients: FakeClients,
) -> None:
    titles = ["Printify US standard", "Printify EU standard"]

    class Profiles(FakeEtsyListingClient):
        """Etsy's profiles as ``titles`` holds them when the page asks."""

        def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]:
            return [ShippingProfile(shipping_profile_id=n, title=t) for n, t in enumerate(titles)]

    fake_clients.etsy_listing = Profiles()
    open_defaults(page, calibrator_server, theme)
    shipping = page.get_by_role("combobox", name="Shipping profile")
    expect(shipping).to_be_enabled()

    # Returning to the page re-reads Etsy's lists through the real endpoint.
    titles.append("Printify UK standard")
    with page.expect_response(lambda r: r.url.endswith("/api/admin/shop/lookups")):
        page.evaluate("window.dispatchEvent(new Event('focus'))")
    with page.expect_response(is_save) as saved:
        page.get_by_role("button", name="Use it").click()
    assert saved.value.request.post_data_json["changes"] == {
        "shipping_profile": "Printify UK standard"
    }
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    expect(shipping).to_have_value("Printify UK standard")
    assert on_disk(workspace_root).etsy.listing_defaults.shipping_profile == "Printify UK standard"
    capture(page, theme, "use-it")

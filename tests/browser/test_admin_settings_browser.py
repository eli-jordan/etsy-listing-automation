"""Admin Settings through the built SPA, real API and fixture files (PR 4).

Wiring only: what the page reads from ``settings.yaml`` and what its
completed edits write there. The save queue's ordering, retry and conflict
rules are Vitest's (``useSaveQueue.test.ts``, ``SettingsPanel.test.tsx``);
revisions and conflicts over HTTP are
``tests/server/behaviour/test_workspace_settings_api.py``'s.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from etsy_listings.core import connections
from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient, FakeEtsyShopClient
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.core.config.settings import Settings
from etsy_listings.core.workspace.workspace import Workspace

pytestmark = pytest.mark.browser


@pytest.fixture
def expect(browser_type):
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


def capture(page, theme: str, state: str) -> None:
    if directory := os.environ.get("ADMIN_SETTINGS_SCREENSHOT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"app-{state}-{theme}.png"))


def open_settings(page, base: str, theme: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme=theme)
    page.goto(f"{base}/admin")
    page.get_by_role("link", name="Settings settings.yaml").click()


def is_save(response) -> bool:
    return response.url.endswith("/api/admin/settings") and response.request.method == "PATCH"


def test_reviewed_market_values_load_without_rewriting_relative_weights(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    source = (
        b"batch_ai:\n  concurrency: 2\nmarket_seo:\n  weights:\n"
        b"    reviews: 0.3\n    favourites_per_day: 0.35\n    search_rank: 0.2\n"
        b"    views_per_day: 0.1\n    shop_sales: 0.05\n    shop_rating: 0\n"
    )
    path.write_bytes(source)
    open_settings(page, calibrator_server, theme)
    expect(page.get_by_role("slider", name="Listings drafted at once")).to_have_value("2")
    expect(page.locator(".sp-legend__pct")).to_have_text(
        ["30%", "35%", "20%", "10%", "5%", "Not counted"]
    )
    assert path.read_bytes() == source
    capture(page, theme, "market")
    page.get_by_role("heading", name="Batch AI").scroll_into_view_if_needed()
    capture(page, theme, "batch")


def test_keyboard_edits_and_reset_persist_only_completed_changes(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    open_settings(page, calibrator_server, theme)
    slider = page.get_by_role("slider", name="Listings drafted at once")
    expect(slider).to_have_value("1")
    assert not path.exists()
    capture(page, theme, "defaults")
    with page.expect_response(is_save) as saved:
        slider.press("ArrowRight")
    assert saved.value.json()["concurrency"] == 2
    divider = page.get_by_role("separator", name="Between Reviews and Favourites per day")
    divider.focus()
    with page.expect_response(is_save):
        divider.press("Shift+ArrowRight")
    weights = Settings.load(path).market_seo.weights
    assert (weights.reviews, weights.favourites_per_day, weights.search_rank) == (35, 25, 20)
    expect(divider).to_be_focused()
    capture(page, theme, "keyboard")
    with page.expect_response(is_save):
        page.get_by_role("button", name="Reset to defaults").click()
    expect(page.get_by_role("button", name="Reset to defaults")).to_be_disabled()
    assert Settings.load(path).market_seo.weights.reviews == 30
    assert Settings.load(path).batch_ai.concurrency == 2
    capture(page, theme, "reset")


def test_relative_zero_shares_are_display_only_until_a_completed_pointer_edit(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    source = (
        b"# seller weights\nmarket_seo:\n  weights:\n    reviews: 0.3\n"
        b"    favourites_per_day: 0\n    search_rank: 0\n    views_per_day: 0.6\n"
        b"    shop_sales: 0.05\n    shop_rating: 0.05\n"
    )
    path.write_bytes(source)
    open_settings(page, calibrator_server, theme)
    expect(page.get_by_role("heading", name="Market SEO scoring")).to_be_visible()
    assert path.read_bytes() == source
    capture(page, theme, "zero")
    # AI providers sit above this panel; a pointer only reaches what is on screen.
    page.locator(".sp-weights").scroll_into_view_if_needed()
    bar = page.locator(".sp-weights").bounding_box()
    assert bar is not None
    x = bar["x"] + bar["width"] * 0.3
    y = bar["y"] + bar["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - bar["width"] * 0.1, y)
    assert path.read_bytes() == source
    with page.expect_response(is_save):
        page.mouse.up()
    weights = Settings.load(path).market_seo.weights
    assert (weights.reviews, weights.favourites_per_day, weights.search_rank) == (20, 10, 0)
    assert path.read_bytes().startswith(b"# seller weights\n")
    assert sum(weights.model_dump().values()) == 100
    capture(page, theme, "pointer")


def test_raising_the_step_raises_the_run_limit_in_the_same_save(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,
) -> None:
    """ADR-0057 through the built page: the floor, the raise and one write."""
    path = Workspace.discover(root_override=workspace_root).settings_file()
    open_settings(page, calibrator_server, theme)
    section = page.get_by_role("region", name="AI time limits")
    step = section.get_by_role("slider", name="Per step")
    run = section.get_by_role("slider", name="Whole run")
    expect(step).to_have_value("5")
    expect(run).to_have_value("20")
    expect(run).to_have_attribute("min", "15")
    section.evaluate("node => node.scrollIntoView({block: 'start'})")
    capture(page, theme, "limits")

    with page.expect_response(is_save) as saved:
        step.fill("10")
        step.blur()
    assert saved.value.ok

    expect(run).to_have_value("30")
    expect(run).to_have_attribute("min", "30")
    expect(section.get_by_role("status")).to_contain_text(
        "Run limit increased from 20 to 30 minutes to allow 3 providers × 10 minutes."
    )
    limits = Settings.load(path).ai
    assert (limits.step_limit_minutes, limits.run_limit_minutes) == (10, 30)
    section.evaluate("node => node.scrollIntoView({block: 'start'})")
    capture(page, theme, "raised")

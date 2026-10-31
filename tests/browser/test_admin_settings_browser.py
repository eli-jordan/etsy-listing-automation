"""Admin Settings through the built SPA, real API and fixture files (PR 4)."""

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
    if directory := os.environ.get("ADMIN_SETTINGS_SCREENSHOT_DIR"):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"app-{state}-{theme}.png"))


def open_settings(page, base: str, theme: str) -> None:  # noqa: ANN001
    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme=theme)
    page.goto(f"{base}/admin")
    page.get_by_role("link", name="Settings settings.yaml").click()


def is_save(response) -> bool:  # noqa: ANN001
    return response.url.endswith("/api/admin/settings") and response.request.method == "PATCH"


def test_reviewed_market_values_load_without_rewriting_relative_weights(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    source = (
        b"batch_ai:\n  concurrency: 2\nmarket_seo:\n  weights:\n"
        b"    reviews: 0.3\n    favourites_per_day: 0.35\n    search_rank: 0.2\n"
        b"    views_per_day: 0.1\n    shop_sales: 0.05\n    shop_rating: 0\n"
    )
    path.write_bytes(source)
    open_settings(page, calibrator_server, theme)
    expect(page.get_by_role("slider")).to_have_value("2")
    expect(page.locator(".sp-legend__pct")).to_have_text(
        ["30%", "35%", "20%", "10%", "5%", "Not counted"]
    )
    assert path.read_bytes() == source
    capture(page, theme, "market")


def test_keyboard_edits_and_reset_persist_only_completed_changes(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
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
    theme: str,  # noqa: ANN001
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


def test_conflict_keeps_the_external_file_and_reload_discards_the_refused_edit(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_bytes(b"batch_ai:\n  concurrency: 2\n")
    open_settings(page, calibrator_server, theme)
    slider = page.get_by_role("slider", name="Listings drafted at once")
    expect(slider).to_have_value("2")
    external = path.read_bytes() + b"# external comment\n"
    path.write_bytes(external)
    with page.expect_response(is_save) as refused:
        slider.press("ArrowRight")
    assert refused.value.status == 409
    expect(slider).to_be_disabled()
    assert path.read_bytes() == external
    capture(page, theme, "conflict")
    page.get_by_role("link", name="Shop shop.yaml").click()
    expect(page.get_by_role("heading", name="Connected shops")).to_be_visible()
    page.get_by_role("link", name="Settings settings.yaml").click()
    page.get_by_role("button", name="Reload settings").click()
    expect(slider).to_be_enabled()
    expect(slider).to_have_value("2")
    assert path.read_bytes() == external


def test_invalid_file_rechecks_and_failed_saves_keep_the_edit_for_retry(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_bytes(b"batch_ai:\n  concurrency: 0\n")
    open_settings(page, calibrator_server, theme)
    expect(page.get_by_role("alert")).to_contain_text("batch_ai.concurrency")
    expect(page.get_by_role("slider")).to_have_count(0)
    capture(page, theme, "invalid")
    page.get_by_role("button", name="Check file again").click()
    expect(page.get_by_role("alert")).to_contain_text("settings.yaml")
    path.write_bytes(b"batch_ai:\n  concurrency: 2\n")
    page.get_by_role("button", name="Check file again").click()
    slider = page.get_by_role("slider", name="Listings drafted at once")
    expect(slider).to_have_value("2")

    def fail_patch(route) -> None:  # noqa: ANN001
        if route.request.method == "PATCH":
            route.fulfill(
                status=503, content_type="application/json", body='{"detail":"disk unavailable"}'
            )
        else:
            route.continue_()

    page.route("**/api/admin/settings", fail_patch)
    slider.press("ArrowRight")
    expect(page.get_by_role("button", name="Retry save")).to_be_visible()
    assert Settings.load(path).batch_ai.concurrency == 2
    expect(slider).to_have_value("3")
    capture(page, theme, "error")
    page.unroute("**/api/admin/settings", fail_patch)
    with page.expect_response(is_save):
        page.get_by_role("button", name="Retry save").click()
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    assert Settings.load(path).batch_ai.concurrency == 3


def test_rapid_actions_use_the_revision_returned_by_the_previous_save(
    page,
    expect,
    calibrator_server: str,
    workspace_root: Path,
    theme: str,  # noqa: ANN001
) -> None:
    open_settings(page, calibrator_server, theme)
    slider = page.get_by_role("slider", name="Listings drafted at once")
    expect(slider).to_have_value("1")
    held = []
    revisions: list[str] = []

    def hold_first(route) -> None:  # noqa: ANN001
        if route.request.method != "PATCH":
            route.continue_()
            return
        revisions.append(route.request.post_data_json["revision"])
        if len(revisions) == 1:
            held.append(route)
        else:
            route.continue_()

    page.route("**/api/admin/settings", hold_first)
    slider.press("ArrowRight")
    expect(page.get_by_role("status")).to_contain_text("Saving")
    slider.press("ArrowRight")
    assert len(revisions) == 1
    first = held[0].fetch()
    next_revision = first.json()["revision"]
    with page.expect_response(
        lambda response: (
            is_save(response) and response.request.post_data_json["changes"]["concurrency"] == 3
        )
    ):
        held[0].fulfill(response=first)
    expect(page.get_by_text("Saved", exact=True)).to_be_visible()
    assert revisions == ["absent", next_revision]
    assert (
        Settings.load(
            Workspace.discover(root_override=workspace_root).settings_file()
        ).batch_ai.concurrency
        == 3
    )
    capture(page, theme, "rapid")

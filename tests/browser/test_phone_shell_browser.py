"""The phone shell, driven with a finger: the bottom tab bar and the bottom
sheet a confirm becomes."""

from __future__ import annotations

import pytest

from tests.support.mobile import assert_mobile_page_fits, swipe

pytestmark = pytest.mark.browser


def _tab_bar_box(page) -> dict:
    return page.locator(".sidebar").bounding_box()


def test_the_tab_bar_sits_at_the_bottom_and_moves_between_pages(phone_page) -> None:
    page = phone_page
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")

    bar = _tab_bar_box(page)
    viewport = page.viewport_size
    assert bar["y"] + bar["height"] == pytest.approx(viewport["height"], abs=1)
    assert bar["width"] == pytest.approx(viewport["width"], abs=1)

    nav = page.locator(".sidebar")
    # Short labels on the bar; the links keep their full names.
    for name in ["Dashboard", "Listings", "Listing Templates", "Mockup Templates", "Admin"]:
        nav.get_by_role("link", name=name, exact=True).wait_for(state="visible")
    assert nav.get_by_role("link", name="Mockup Templates").inner_text().strip() == "Mockups"

    nav.get_by_role("link", name="Listings", exact=True).tap()
    page.get_by_role("heading", name="Listings").wait_for(state="visible")
    assert "nav-item--active" in (
        nav.get_by_role("link", name="Listings", exact=True).get_attribute("class") or ""
    )
    assert_mobile_page_fits(page)

    # The bar stays put while the page scrolls under it.
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(200)
    assert _tab_bar_box(page)["y"] == pytest.approx(bar["y"], abs=1)


def test_a_confirm_is_a_bottom_sheet_that_a_swipe_down_dismisses(phone_page) -> None:
    page = phone_page
    origin = page.url.rstrip("/")
    page.goto(f"{origin}/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")

    page.get_by_role("button", name="Delete", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible")
    # The sheet slides up; measure where it comes to rest.
    page.wait_for_function("() => document.getAnimations().length === 0")
    sheet = page.locator(".modal-dialog")
    box = sheet.bounding_box()
    viewport = page.viewport_size
    assert box["y"] + box["height"] == pytest.approx(viewport["height"], abs=1)
    assert box["width"] == pytest.approx(viewport["width"], abs=1)

    grabber = page.locator(".sheet-grabber").bounding_box()
    x = grabber["x"] + grabber["width"] / 2
    y = grabber["y"] + grabber["height"] / 2
    swipe(page, (x, y), (x, y + 260))
    dialog.wait_for(state="detached")

    # Dismissed, not confirmed: the listing is still there to delete.
    page.get_by_role("button", name="Delete", exact=True).wait_for(state="visible")

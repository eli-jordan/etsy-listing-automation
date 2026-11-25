"""A phone held sideways, driven with a finger: 844px wide, so wider than the
phone width, but short and touch-driven, so it gets the phone layout with
the tab bar turned into a rail down the left edge.

A short desktop window (a mouse, not a finger) keeps the desktop layout.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.support.mobile import assert_mobile_page_fits, swipe

pytestmark = pytest.mark.browser


def _origin(page) -> str:
    return page.url.rstrip("/")


def test_the_tab_bar_is_a_rail_down_the_left_edge(phone_landscape_page) -> None:
    page = phone_landscape_page
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")

    viewport = page.viewport_size
    rail = page.locator(".sidebar").bounding_box()
    assert rail["x"] == pytest.approx(0, abs=1)
    assert rail["height"] == pytest.approx(viewport["height"], abs=1)
    assert rail["width"] < 120
    # The page starts beside the rail, not under it.
    heading = page.get_by_role("heading", name="Dashboard").bounding_box()
    assert heading["x"] >= rail["x"] + rail["width"]

    nav = page.locator(".sidebar")
    for name in ["Dashboard", "Listings", "Listing Templates", "Mockup Templates", "Admin"]:
        link = nav.get_by_role("link", name=name, exact=True)
        link.wait_for(state="visible")
        box = link.bounding_box()
        assert box["y"] >= 0
        assert box["y"] + box["height"] <= viewport["height"]
    assert nav.get_by_role("link", name="Mockup Templates").inner_text().strip() == "Mockups"

    nav.get_by_role("link", name="Listings", exact=True).tap()
    page.get_by_role("heading", name="Listings").wait_for(state="visible")
    assert_mobile_page_fits(page)
    # Nothing is pinned to the bottom of the screen any more.
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(200)
    assert page.locator(".sidebar").bounding_box()["y"] == pytest.approx(0, abs=1)


def test_a_short_desktop_window_keeps_the_desktop_layout(browser_type, calibrator_server) -> None:
    context = browser_type.new_context(viewport={"width": 1200, "height": 460})
    page = context.new_page()
    try:
        page.goto(calibrator_server)
        page.get_by_role("heading", name="Dashboard").wait_for(state="visible")
        nav = page.locator(".sidebar")
        expect(nav.locator(".sidebar__brand")).to_be_visible()
        link = nav.get_by_role("link", name="Mockup Templates")
        assert link.inner_text().strip() == "Mockup Templates"
    finally:
        context.close()


def test_listings_put_new_listing_in_the_head_and_search_beside_the_chips(
    phone_landscape_page,
) -> None:
    page = phone_landscape_page
    page.goto(f"{_origin(page)}/listings")
    page.get_by_role("heading", name="Listings").wait_for(state="visible")

    # So few rows show sideways that a floating button would sit on one.
    expect(page.locator(".m-fab")).to_have_count(0)
    new = page.locator(".page-head").get_by_role("button", name="+ New listing")
    title = page.get_by_role("heading", name="Listings").bounding_box()
    assert new.bounding_box()["y"] < title["y"] + title["height"]

    search = page.get_by_placeholder("Search listings…").bounding_box()
    chip = page.get_by_role("radio", name=re.compile("^All")).bounding_box()
    assert abs((search["y"] + search["height"] / 2) - (chip["y"] + chip["height"] / 2)) < 4
    new.tap()
    page.wait_for_url("**/listings/new")


def test_a_sheet_rises_in_the_middle_and_a_swipe_down_dismisses_it(
    phone_landscape_page,
) -> None:
    page = phone_landscape_page
    page.goto(f"{_origin(page)}/listings")
    page.get_by_role("button", name="More actions for take-a-hike").tap()
    sheet = page.get_by_role("dialog", name="take-a-hike", exact=True)
    sheet.wait_for(state="visible")
    page.wait_for_function("() => document.getAnimations().length === 0")

    viewport = page.viewport_size
    box = page.locator(".modal-dialog").bounding_box()
    assert box["width"] <= 600
    assert box["x"] + box["width"] / 2 == pytest.approx(viewport["width"] / 2, abs=2)
    assert box["y"] + box["height"] == pytest.approx(viewport["height"], abs=1)
    assert box["y"] >= 0

    grabber = page.locator(".sheet-grabber").bounding_box()
    x = grabber["x"] + grabber["width"] / 2
    y = grabber["y"] + grabber["height"] / 2
    swipe(page, (x, y), (x, y + 200))
    sheet.wait_for(state="detached")


def _middle(box: dict) -> float:
    return box["y"] + box["height"] / 2


def test_the_editor_head_is_one_row_and_the_shirt_sits_beside_its_colours(
    phone_landscape_page,
) -> None:
    page = phone_landscape_page
    page.goto(f"{_origin(page)}/listings/take-a-hike")
    title = page.get_by_role("heading", name="take-a-hike")
    title.wait_for(state="visible")

    head = page.locator(".page-head--editor").bounding_box()
    assert head["height"] < 64
    for control in (
        page.locator(".page-head--editor .page-head__crumb"),
        title,
        page.get_by_role("button", name="Deploy changes →"),
        page.get_by_role("button", name="More actions"),
    ):
        assert abs(_middle(control.bounding_box()) - _middle(head)) < 16

    # The tabs are on the first screen even under the issues banner, and
    # Variants puts the shirt beside its colours rather than over them.
    viewport = page.viewport_size
    tabs = page.locator(".tabs").bounding_box()
    assert tabs["y"] + tabs["height"] <= viewport["height"]
    shirt = page.locator(".layout--variants > .variants-preview")
    colours = page.locator(".layout--variants > fieldset").bounding_box()
    assert shirt.bounding_box()["x"] + shirt.bounding_box()["width"] <= colours["x"] + 1

    # The shirt stays in view while the colours scroll.
    page.mouse.wheel(0, 800)
    page.wait_for_timeout(300)
    held = shirt.bounding_box()
    assert held["y"] >= 0
    assert held["y"] + held["height"] <= viewport["height"] + 1
    assert_mobile_page_fits(page)


def test_mockups_keep_the_photo_beside_the_controls(phone_landscape_page) -> None:
    page = phone_landscape_page
    page.goto(f"{_origin(page)}/templates")
    page.locator(".tswitch__name").wait_for(state="visible")

    viewport = page.viewport_size
    photo = page.locator(".quad-editor__image").first
    photo.wait_for(state="visible")
    page.wait_for_function(
        "() => [...document.querySelectorAll('.quad-editor__image')].every((i) => i.complete)"
    )
    box = photo.bounding_box()
    switcher = page.locator(".tswitch").bounding_box()
    # The whole photo on the screen, with the controls in a column beside it.
    assert box["y"] >= 0
    assert box["y"] + box["height"] <= viewport["height"] + 1
    assert box["x"] + box["width"] <= switcher["x"] + 1
    corner = page.locator(".quad-editor__grip[data-corner='0']").bounding_box()
    assert corner["y"] >= 0
    assert corner["y"] + corner["height"] <= viewport["height"] + 1
    assert_mobile_page_fits(page)

"""The listing editor on a phone, driven with a finger: the compact head and
its "⋯" sheet, one sticky row of tabs that also swipes, the gallery alone
with Add media and Adjust as sheets, tap-to-move reordering, and the
lightbox's swipes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.support.ai_runs import serve_running_ai_run
from tests.support.mobile import PHONE_CONTEXT, assert_mobile_page_fits, swipe

pytestmark = pytest.mark.browser


def _open_editor(page, tab: str | None = None) -> None:
    origin = page.url.rstrip("/")
    page.goto(f"{origin}/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    if tab is not None:
        page.locator(".tabs .seg-opt", has_text=tab).tap()


def _active_tab(page) -> str:
    # The first line: a tab may also carry its issue count.
    return page.locator(".tabs .seg-opt--on").inner_text().strip().splitlines()[0]


def _colours(listing: Path) -> list[str]:
    media = yaml.safe_load(listing.read_text(encoding="utf-8"))["media"]
    return [entry["colour"] for entry in media]


def _swipe_content(page, dx: float) -> None:
    box = page.locator(".editor-pager").bounding_box()
    # Near the top: the fieldset legend, not a field, which keeps its own drag.
    y = box["y"] + 14
    start = 330 if dx < 0 else 60
    swipe(page, (start, y), (start + dx, y))
    page.wait_for_timeout(400)


def _middle(box: dict) -> float:
    return box["y"] + box["height"] / 2


def test_the_head_is_compact_with_the_other_actions_behind_more(phone_page) -> None:
    page = phone_page
    _open_editor(page)
    head = page.locator(".page-head--editor").bounding_box()
    # Back and "⋯" on the bar line, the title under them, then the state
    # line -- not a screenful of actions.
    assert head["height"] < 190
    back = page.locator(".page-head--editor .page-head__crumb").bounding_box()
    more = page.get_by_role("button", name="More actions").bounding_box()
    title = page.get_by_role("heading", name="take-a-hike").bounding_box()
    deploy = page.get_by_role("button", name="Deploy changes →").bounding_box()
    assert abs(_middle(back) - _middle(more)) < 12
    assert title["y"] >= back["y"] + back["height"] - 2
    assert deploy["y"] >= title["y"] + title["height"] - 2
    assert not page.get_by_role("button", name="Create listing template").is_visible()

    page.get_by_role("button", name="More actions").tap()
    sheet = page.get_by_role("dialog", name="take-a-hike")
    sheet.get_by_role("button", name="Create listing template").wait_for(state="visible")
    sheet.get_by_role("button", name="Done").tap()
    sheet.wait_for(state="hidden")
    assert_mobile_page_fits(page)


def test_the_tabs_are_one_sticky_row_that_the_content_swipes(phone_page) -> None:
    page = phone_page
    _open_editor(page)
    tabs = page.locator(".tabs .seg-opt")
    boxes = [tabs.nth(i).bounding_box() for i in range(tabs.count())]
    assert len({round(box["y"]) for box in boxes}) == 1
    assert all(box["height"] >= 40 for box in boxes)

    _swipe_content(page, -240)
    assert _active_tab(page) == "Pricing"
    _swipe_content(page, 240)
    assert _active_tab(page) == "Variants"
    # Past the first tab there is nowhere to go.
    _swipe_content(page, 240)
    assert _active_tab(page) == "Variants"

    page.mouse.wheel(0, 1500)
    page.wait_for_timeout(300)
    assert page.locator(".tabs").bounding_box()["y"] < 20
    assert_mobile_page_fits(page)


def _open_full_size(page, tile: int = 0) -> None:
    """A tile's full-size view, from its bar's View."""
    page.locator(".rtile__face").nth(tile).tap()
    page.locator(".reel-moves").get_by_role("button", name="View").tap()


def test_the_gallery_stands_alone_and_a_tap_reorders_it(phone_page, workspace_root: Path) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    page.locator(".reel").wait_for(state="visible")
    # No preview pane a scroll below the gallery: Adjust opens it in a sheet.
    assert page.locator(".preview-pane").count() == 0
    assert not page.get_by_role("button", name="Files", exact=True).is_visible()

    page.get_by_role("button", name="Add media").tap()
    sheet = page.get_by_role("dialog", name="Add media")
    sheet.get_by_role("button", name="Files", exact=True).wait_for(state="visible")
    sheet.get_by_role("button", name="Done").tap()
    sheet.wait_for(state="hidden")

    page.locator(".rtile__face").nth(1).tap()
    bar = page.get_by_role("group", name="Move flat-lay-01 · blue-jean")
    bar.get_by_role("button", name="Move later").tap()
    page.wait_for_timeout(300)
    page.get_by_role("group", name="Move flat-lay-01 · blue-jean").get_by_text("Image 3").wait_for(
        state="visible"
    )

    listing = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    expected = ["black", "ivory", "blue-jean", "moss"]
    for _ in range(50):
        if _colours(listing) == expected:
            break
        page.wait_for_timeout(200)
    assert _colours(listing) == expected
    assert_mobile_page_fits(page)


def test_the_lightbox_swipes_between_images_and_down_to_close(phone_page) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    _open_full_size(page)
    count = page.locator(".lightbox__count")
    count.wait_for(state="visible")
    assert count.inner_text() == "1 / 4"

    swipe(page, (330, 450), (60, 450))
    page.wait_for_timeout(400)
    assert count.inner_text() == "2 / 4"
    swipe(page, (60, 450), (330, 450))
    page.wait_for_timeout(400)
    assert count.inner_text() == "1 / 4"

    swipe(page, (195, 300), (195, 700))
    page.locator(".lightbox").wait_for(state="detached")


def test_a_pinch_zoomed_lightbox_pans_rather_than_paging_or_closing(phone_page) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    _open_full_size(page)
    count = page.locator(".lightbox__count")
    count.wait_for(state="visible")

    session = page.context.new_cdp_session(page)
    try:
        session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2.5})
        page.wait_for_function("() => visualViewport.scale > 2")
        swipe(page, (330, 450), (60, 450))
        page.wait_for_timeout(400)
        # The finger panned the zoomed view instead of turning the page.
        assert page.evaluate("visualViewport.offsetLeft") > 50
        assert count.inner_text() == "1 / 4"
        page.evaluate("window.scrollTo(0, 0)")
        swipe(page, (195, 300), (195, 700))
        page.wait_for_timeout(400)
        assert page.locator(".lightbox").count() == 1

        # Zoomed out again, the swipes work as before.
        session.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})
        page.wait_for_function("() => visualViewport.scale === 1")
        swipe(page, (330, 450), (60, 450))
        page.wait_for_timeout(400)
        assert count.inner_text() == "2 / 4"
    finally:
        session.detach()


def test_details_fields_are_full_width_under_their_labels(phone_page) -> None:
    page = phone_page
    _open_editor(page, "Listing Details")
    title = page.locator("#details-title").bounding_box()
    field = page.locator(".field:has(#details-title)").bounding_box()
    assert title["width"] == pytest.approx(field["width"], abs=2)
    count = page.locator(".field:has(#details-title) .field__count").bounding_box()
    assert count["y"] + count["height"] <= title["y"]

    brief = page.locator("#details-brief").bounding_box()
    ai = page.locator(".seo-ai-mode-anchor").bounding_box()
    assert ai["y"] >= brief["y"] + brief["height"]
    assert_mobile_page_fits(page)


def test_a_failed_action_from_the_more_sheet_shows_under_the_head(phone_page) -> None:
    page = phone_page

    def refuse_delete(route) -> None:
        if route.request.method == "DELETE":
            route.fulfill(status=500, json={"detail": "no"})
        else:
            route.fallback()

    page.route("**/api/listings/take-a-hike", refuse_delete)
    _open_editor(page)
    page.get_by_role("button", name="More actions").tap()
    sheet = page.get_by_role("dialog", name="take-a-hike", exact=True)
    sheet.locator(".action-link--danger").tap()
    sheet.wait_for(state="hidden")
    confirm = page.get_by_role("dialog")
    confirm.get_by_role("button").filter(has_text="elet").last.tap()

    alert = page.get_by_role("alert").filter(has_text="Could not")
    alert.wait_for(state="visible")
    head = page.locator(".page-head--editor").bounding_box()
    box = alert.bounding_box()
    assert box["y"] >= head["y"] + head["height"] - 1
    assert box["y"] + box["height"] <= page.viewport_size["height"]


def test_fix_opens_its_tab_right_under_the_tab_strip(phone_page) -> None:
    page = phone_page
    page.goto(f"{page.url.rstrip('/')}/listings/new")
    page.locator(".issues").wait_for(state="visible")
    page.get_by_role("button", name="Show").tap()
    page.locator(".issue__fix", has_text="Fix").last.tap()
    page.wait_for_timeout(500)

    assert _active_tab(page) == "Details"
    # The list folded again, and the tab starts right under the strip.
    assert page.locator(".issue").count() == 0
    tabs = page.locator(".tabs").bounding_box()
    content = page.locator(".editor-pager").bounding_box()
    assert tabs["y"] >= 0
    assert content["y"] - (tabs["y"] + tabs["height"]) < 24
    assert_mobile_page_fits(page)


def test_a_selected_tile_opens_full_size_and_can_be_let_go(phone_page) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    tile = page.locator(".rtile__face").nth(2)
    tile.tap()
    bar = page.locator(".reel-moves")
    bar.wait_for(state="visible")

    bar.get_by_role("button", name="View").tap()
    count = page.locator(".lightbox__count")
    count.wait_for(state="visible")
    assert count.inner_text() == "3 / 4"
    page.keyboard.press("Escape")
    page.locator(".lightbox").wait_for(state="detached")
    # Escape closed the full-size view, not the selection under it.
    assert bar.is_visible()

    bar.get_by_role("button", name="Done").tap()
    bar.wait_for(state="detached")
    tile.tap()
    bar.wait_for(state="visible")
    tile.tap()
    bar.wait_for(state="detached")
    tile.tap()
    bar.wait_for(state="visible")
    page.keyboard.press("Escape")
    bar.wait_for(state="detached")


def test_the_tabs_and_their_issue_counts_fit_a_320px_screen(
    browser_type, calibrator_server: str
) -> None:
    context = browser_type.new_context(
        **{**PHONE_CONTEXT, "viewport": {"width": 320, "height": 568}}
    )
    try:
        page = context.new_page()
        page.goto(f"{calibrator_server}/listings/new")
        page.locator(".tabs .tab-badge").first.wait_for(state="visible")
        layout = page.evaluate(
            """() => [...document.querySelectorAll('.tabs .seg-opt')].map((tab) => {
              const range = document.createRange();
              range.selectNodeContents(tab);
              const text = range.getBoundingClientRect();
              const box = tab.getBoundingClientRect();
              return {left: box.left, right: box.right, textLeft: text.left, textRight: text.right};
            })"""
        )
        assert len(layout) == 4
        assert layout[-1]["right"] <= 320
        for tab in layout:
            # Each label and its count inside its own tab, clear of the
            # next one's label.
            assert tab["textLeft"] >= tab["left"] + 1
            assert tab["textRight"] <= tab["right"] - 1
        assert page.locator(".tabs .tab-badge").count() >= 2
        assert_mobile_page_fits(page)
    finally:
        context.close()


def test_the_ai_failure_toast_stays_put_while_the_tab_is_swiped(phone_page) -> None:
    page = phone_page
    serve_running_ai_run(page, "take-a-hike", stream_fails=True)
    _open_editor(page, "Listing Details")
    toast = page.locator(".ai-failure-toast")
    toast.wait_for(state="visible")
    page.wait_for_timeout(400)  # its slide in
    before = toast.bounding_box()

    box = page.locator(".editor-pager").bounding_box()
    y = box["y"] + 14
    session = page.context.new_cdp_session(page)
    try:
        session.send(
            "Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 330, "y": y}]}
        )
        for step in range(1, 7):
            point = {"x": 330 - step * 15, "y": y}
            session.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [point]})
            page.wait_for_timeout(16)
        page.wait_for_timeout(100)
        # The tab content is mid-drag; the toast is not part of it.
        assert page.evaluate("document.querySelector('.editor-pager').style.transform") != ""
        during = toast.bounding_box()
        session.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        session.detach()
    assert during["x"] == pytest.approx(before["x"], abs=1)
    assert during["y"] == pytest.approx(before["y"], abs=1)


def test_adjust_opens_the_preview_in_a_sheet_ready_to_position(phone_page) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    page.locator(".rtile__face").first.tap()
    page.locator(".reel-moves").get_by_role("button", name="Adjust").tap()

    sheet = page.get_by_role("dialog", name="flat-lay-01 · black")
    switch = sheet.get_by_role("switch", name="Adjust position")
    switch.wait_for(state="visible")
    assert switch.get_attribute("aria-checked") == "true"
    page.wait_for_timeout(500)  # the sheet's slide up
    # The whole picture on screen, under the sheet's title.
    stage = sheet.locator(".preview-stage").bounding_box()
    assert stage["y"] + stage["height"] <= page.viewport_size["height"]

    sheet.get_by_role("button", name="Done").tap()
    sheet.wait_for(state="detached")
    assert page.locator(".reel-moves").is_visible()

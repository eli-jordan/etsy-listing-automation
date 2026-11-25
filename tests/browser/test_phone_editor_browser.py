"""The listing editor on a phone, driven with a finger: the compact head and
its "⋯" sheet, one sticky row of tabs that also swipes, the gallery first
with Add media as a sheet, tap-to-move reordering, and the lightbox's
swipes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.support.mobile import assert_mobile_page_fits, swipe

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


def test_the_gallery_comes_first_and_a_tap_reorders_it(phone_page, workspace_root: Path) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    reel = page.locator(".reel").bounding_box()
    preview = page.locator(".preview-pane").bounding_box()
    assert reel["y"] < preview["y"]
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
    page.locator(".rtile__face").first.tap()
    page.locator(".preview-stage__open").tap()
    count = page.locator(".lightbox__count")
    count.wait_for(state="visible")
    assert count.inner_text() == "1 / 4"

    swipe(page, (330, 450), (60, 450))
    page.wait_for_timeout(200)
    assert count.inner_text() == "2 / 4"
    swipe(page, (60, 450), (330, 450))
    page.wait_for_timeout(200)
    assert count.inner_text() == "1 / 4"

    swipe(page, (195, 300), (195, 700))
    page.locator(".lightbox").wait_for(state="detached")


def test_a_pinch_zoomed_lightbox_pans_rather_than_paging_or_closing(phone_page) -> None:
    page = phone_page
    _open_editor(page, "Listing Images")
    page.locator(".rtile__face").first.tap()
    page.locator(".preview-stage__open").tap()
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
        page.wait_for_timeout(200)
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

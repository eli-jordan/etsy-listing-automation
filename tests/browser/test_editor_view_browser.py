"""Browser test for a refresh of the listing editor: that a real reload comes
back to the tab and the picture the seller was looking at.

The Vitest layer can only remount the component. A reload is what this needs:
a new document, the listing fetched again, the template and file lists answered
by the real API, and `sessionStorage` kept by the browser rather than by jsdom.
Skips cleanly when playwright or its chromium build is missing (`conftest.py`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.support.marigold import wait_until

pytestmark = pytest.mark.browser

IMAGES = Path(__file__).parent.parent / "fixtures" / "workspace" / "designs"


def _removed(path: Path) -> bool:
    """Whether ``path`` could be deleted: Windows refuses while the server is
    still streaming it to the page, which a busy machine makes likely."""
    try:
        path.unlink()
    except PermissionError:
        return False
    return True


def _open_listing(page) -> None:
    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")


def _open_images(page) -> None:
    page.locator(".tabs .seg-opt", has_text="Images").click()
    page.locator(".locator").wait_for(state="visible")


def _active_tab(page) -> str:
    # The first line: an issue count badge follows the label.
    return page.locator(".tabs .seg-opt--on").inner_text().splitlines()[0]


def _wait_for_picture(page, selector: str) -> None:
    """A real decoded image, not only an `<img>` that names one: a restored
    focus that pointed at nothing would still render the element."""
    page.wait_for_function(
        """selector => {
            const image = document.querySelector(selector);
            return image !== null && image.complete && image.naturalWidth > 0;
        }""",
        arg=selector,
    )


def test_a_reload_keeps_the_tab_and_the_picture_in_the_preview(page) -> None:
    _open_listing(page)
    _open_images(page)
    page.locator(".rtile__face").nth(2).click()
    title = page.locator(".preview-meta__title")
    title.wait_for(state="visible")
    chosen = title.inner_text()

    page.reload()

    page.locator(".locator").wait_for(state="visible")
    assert _active_tab(page) == "Listing Images"
    title.wait_for(state="visible")
    assert title.inner_text() == chosen
    _wait_for_picture(page, ".preview-stage__open img")
    # The reel agrees with the stage, so it is the same picture and not only
    # the same words.
    assert page.locator(".rtile").nth(2).get_attribute("class") == "rtile rtile--selected"


def test_a_reload_comes_back_to_where_the_page_was_scrolled(page) -> None:
    """The browser's own restoration runs before the listing has loaded, when
    the page is too short to scroll, so it lands at the top with the preview
    below the fold."""
    _open_listing(page)
    _open_images(page)
    page.locator(".rtile__face").nth(2).click()
    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_function("() => window.scrollY === 500")
    # The listener's write, which is what the reload will read.
    page.wait_for_function(
        "() => sessionStorage.getItem('editor-view:listing:take-a-hike:scroll') === '500'"
    )

    page.reload()

    page.locator(".locator").wait_for(state="visible")
    page.wait_for_function("() => window.scrollY === 500")


def test_a_reload_keeps_a_file_and_the_files_half_of_the_locator(
    page, workspace_root: Path
) -> None:
    (workspace_root / "common-media").mkdir()
    design = next(path for path in IMAGES.iterdir() if path.suffix == ".png")
    shutil.copy(design, workspace_root / "common-media" / "sizing.png")

    _open_listing(page)
    _open_images(page)
    files = page.get_by_role("button", name="Files", exact=True)
    files.click()
    page.get_by_role("button", name="sizing.png").hover()
    title = page.locator(".preview-meta__title")
    title.wait_for(state="visible")
    assert title.inner_text() == "sizing"

    page.reload()

    title.wait_for(state="visible")
    assert title.inner_text() == "sizing"
    assert files.get_attribute("aria-pressed") == "true"
    _wait_for_picture(page, ".preview-stage__open img")


def test_a_reload_keeps_the_colour_on_the_variants_stage(page) -> None:
    _open_listing(page)
    page.get_by_role("button", name="Preview ivory").click()
    selected = page.locator(".color-row--selected .color-row__name")
    assert selected.inner_text() == "ivory"

    page.reload()

    page.get_by_role("button", name="Preview ivory").wait_for(state="visible")
    assert _active_tab(page) == "Variants"
    assert selected.inner_text() == "ivory"


def test_a_reload_keeps_the_lightbox_on_the_picture_it_had_reached(page) -> None:
    _open_listing(page)
    _open_images(page)
    page.locator(".rtile__face").first.click()
    page.locator(".preview-stage__open").click()
    count = page.locator(".lightbox__count")
    count.wait_for(state="visible")
    page.keyboard.press("ArrowRight")
    assert count.inner_text().startswith("2 / ")

    page.reload()

    count.wait_for(state="visible")
    assert count.inner_text().startswith("2 / ")
    _wait_for_picture(page, ".lightbox__image")


def test_a_view_picture_that_has_gone_leaves_the_stage_empty(page, workspace_root: Path) -> None:
    (workspace_root / "common-media").mkdir()
    design = next(path for path in IMAGES.iterdir() if path.suffix == ".png")
    shared = workspace_root / "common-media" / "sizing.png"
    shutil.copy(design, shared)

    _open_listing(page)
    _open_images(page)
    page.get_by_role("button", name="Files", exact=True).click()
    page.get_by_role("button", name="sizing.png").hover()
    page.locator(".preview-meta__title").wait_for(state="visible")
    wait_until(lambda: _removed(shared), "the server letting go of the picture")

    page.reload()

    page.locator(".locator").wait_for(state="visible")
    page.get_by_text("Point at something on the left").wait_for(state="visible")


def test_a_new_browser_tab_starts_from_the_editors_default(page) -> None:
    """`sessionStorage` is one browser tab's: a listing opened fresh is not
    held to the view some other tab was left on."""
    _open_listing(page)
    _open_images(page)

    other = page.context.new_page()
    other.goto(page.url)
    other.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    assert _active_tab(other) == "Variants"

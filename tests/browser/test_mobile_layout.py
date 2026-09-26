"""Mobile layout regression over the production-built SPA.

The shell and each workflow are exercised through the same FastAPI/browser
boundary as a real ``etsy-listings ui`` session. The fixture run is local and
fake-backed by the browser suite; no remote client is called.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.browser

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def _assert_mobile_page_fits(page) -> None:  # noqa: ANN001
    dimensions = page.evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            main: (() => {
                const rect = document.querySelector('main').getBoundingClientRect();
                return {left: rect.left, right: rect.right, width: rect.width};
            })(),
            overflowing: [...document.querySelectorAll('*')]
                .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
                .slice(0, 10)
                .map((element) => ({
                    tag: element.tagName,
                    className: element.className,
                    right: element.getBoundingClientRect().right,
                })),
        })"""
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"], dimensions
    assert dimensions["main"]["left"] <= 1, dimensions
    assert dimensions["main"]["right"] <= dimensions["innerWidth"] + 1, dimensions
    assert dimensions["main"]["width"] >= dimensions["innerWidth"] - 1, dimensions

    navigation = page.get_by_role("navigation")
    navigation.get_by_role("link", name="Dashboard").wait_for(state="visible")
    navigation.get_by_role("link", name="Listings").wait_for(state="visible")


def test_mobile_shell_keeps_listing_workflows_usable_without_page_overflow(
    page,  # noqa: ANN001
    workspace_root: Path,
) -> None:
    common_media = workspace_root / "common-media"
    common_media.mkdir()
    shutil.copy(VIDEOS / "valid-3s-512.mp4", common_media / "size-guide.mp4")

    listing_path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    listing = yaml.safe_load(listing_path.read_text(encoding="utf-8"))
    listing["media"].insert(1, "common-media/size-guide.mp4")
    listing_path.write_text(yaml.safe_dump(listing, sort_keys=False), encoding="utf-8")

    page.set_viewport_size(MOBILE_VIEWPORT)
    origin = page.url.split("/templates", 1)[0]

    page.goto(origin)
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")
    _assert_mobile_page_fits(page)

    page.get_by_role("navigation").get_by_role("link", name="Listings").click()
    page.get_by_role("heading", name="Listings").wait_for(state="visible")
    page.get_by_role("button", name="+ New listing").wait_for(state="visible")
    _assert_mobile_page_fits(page)

    page.goto(f"{origin}/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    page.locator(".tabs .seg-opt", has_text="Listing Images").click()
    page.locator(".rtile video").wait_for(state="visible")
    page.get_by_role("button", name="Files", exact=True).wait_for(state="visible")
    _assert_mobile_page_fits(page)

    page.get_by_role("button", name="Deploy changes →").click()
    page.wait_for_url("**/listings/take-a-hike/deploy")
    page.get_by_role("heading", name="Deploy").wait_for(state="visible")
    page.get_by_text("Render mockups").wait_for(state="visible")
    _assert_mobile_page_fits(page)

"""Browser test for videos in the listing gallery (PRD 71, 72): that the
React reel, the media-files endpoints and the real `listing.yaml` agree about
where a video sits, and that the browser really decodes the file the API
serves.

One sequence over the real SPA and FastAPI: add a shared video and one of the
listing's own, drag the second among the images, wait for autosave, then read
`media:` off disk. Skips cleanly when playwright or its chromium build is
missing (`conftest.py`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.browser

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
FIXTURE_WIDTH = 512
"""`valid-3s-512.mp4`'s pixel width (`scripts/generate_test_assets.py`)."""

SHARED = "common-media/size-guide.mp4"
OWN = "./how-it-fits.mp4"


def _image(colour: str) -> dict[str, str]:
    return {"template": "flat-lay-01", "colour": colour}


def _media_on_disk(workspace_root: Path) -> list[object]:
    path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    media: list[object] = yaml.safe_load(path.read_text(encoding="utf-8"))["media"]
    return media


def _wait_for_media(page, workspace_root: Path, expected: list[object]) -> None:  # noqa: ANN001
    """Poll the file, not the page: "Autosaved" already reads true during the
    debounce before the save is sent (see `test_listings_browser.py`)."""
    for _ in range(100):
        if _media_on_disk(workspace_root) == expected:
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"media: never reached {expected}: {_media_on_disk(workspace_root)}")


def test_add_two_videos_drag_the_second_and_autosave_the_gallery(
    page,  # noqa: ANN001
    workspace_root: Path,
) -> None:
    (workspace_root / "common-media").mkdir()
    shutil.copy(VIDEOS / "valid-3s-512.mp4", workspace_root / SHARED)
    shutil.copy(VIDEOS / "valid-3s-512.mp4", workspace_root / "listings" / "take-a-hike" / OWN[2:])

    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    page.locator(".tabs .seg-opt", has_text="Images").click()
    page.get_by_role("button", name="Files", exact=True).click()

    # The first video lands at position 2, where Etsy pins the featured one.
    page.get_by_role("button", name="size-guide.mp4").click()
    black, blue_jean, ivory, moss = (_image(c) for c in ("black", "blue-jean", "ivory", "moss"))
    _wait_for_media(page, workspace_root, [black, SHARED, blue_jean, ivory, moss])

    # The second goes on the end, from the listing's own directory (PRD 72).
    page.get_by_role("button", name="how-it-fits.mp4").click()
    _wait_for_media(page, workspace_root, [black, SHARED, blue_jean, ivory, moss, OWN])

    reel = page.locator(".rtile")
    featured = reel.nth(1)
    assert "Featured · shown 2nd" in (featured.text_content() or "")

    # Drag the second video among the images: onto position 4.
    reel.nth(5).drag_to(reel.nth(3))
    _wait_for_media(page, workspace_root, [black, SHARED, blue_jean, OWN, ivory, moss])

    # The browser decoded the clip the API served, at the fixture's own size.
    width = featured.locator("video").evaluate(
        """clip => new Promise(resolve => {
            if (clip.readyState >= 1) resolve(clip.videoWidth);
            else clip.addEventListener("loadedmetadata", () => resolve(clip.videoWidth));
        })"""
    )
    assert width == FIXTURE_WIDTH

"""Browser tests for a listing's artwork (multi-artwork plan, PRs 2 and 3):
unlink, pick both files, reload and see both; link a pair of two files and
choose one; give Moss its own design and take it back. Asserted on the
`listing.yaml` the UI wrote and on pictures the browser actually decoded,
like the rest of this layer.

Acceptance 2 (switch to light/dark and pick both), 3 (a partial pair
survives a reload) and 4 (a colour's own file, and back).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from tests.support.builders import edit_listing
from tests.support.scenes import expected_scene

pytestmark = pytest.mark.browser

HIKE = "designs/take-a-hike.png"
DARK_INK = "designs/dark-ink.png"
LIGHT_INK = "designs/light-ink.png"


def _designs(workspace_root: Path) -> None:
    for ref in (DARK_INK, LIGHT_INK):
        shutil.copy(workspace_root / HIKE, workspace_root / ref)


def _design(workspace_root: Path) -> Any:  # noqa: ANN401
    document = yaml.safe_load(
        (workspace_root / "listings" / "take-a-hike" / "listing.yaml").read_text(encoding="utf-8")
    )
    return document.get("design")


def _wait_for_design(page: Any, workspace_root: Path, expected: object) -> None:  # noqa: ANN401
    """Poll the file: the page's "Saved" caption is already true during the
    debounce, so the file is the observable effect to wait on."""
    for _ in range(100):
        if _design(workspace_root) == expected:
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"design never reached {expected}: {_design(workspace_root)}")


def _open(page: Any) -> None:  # noqa: ANN401
    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")


def _card(page: Any, title: str) -> Any:  # noqa: ANN401
    return page.locator(".design-row--slot", has=page.get_by_text(title, exact=True))


def _pick_recent(page: Any, name: str) -> None:  # noqa: ANN401
    page.locator(".add-panel").get_by_role("button", name=re.compile(rf"^{name} ")).click()


def test_unlink_pick_both_files_and_reload(page: Any, workspace_root: Path) -> None:  # noqa: ANN401
    _designs(workspace_root)
    _open(page)

    page.get_by_role("button", name="Unlink").click()
    _wait_for_design(page, workspace_root, {"on-light": HIKE, "on-dark": HIKE})

    page.get_by_role("button", name="Change design for light shirts").click()
    _pick_recent(page, "dark-ink")
    page.get_by_role("button", name="Change design for dark shirts").click()
    _pick_recent(page, "light-ink")
    _wait_for_design(page, workspace_root, {"on-light": DARK_INK, "on-dark": LIGHT_INK})

    page.reload()
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    assert "dark-ink" in _card(page, "For light shirts").inner_text()
    assert "light-ink" in _card(page, "For dark shirts").inner_text()
    assert page.get_by_role("button", name="Link", exact=True).is_visible()

    # The stage renders the previewed colour with its resolved file, and the
    # browser really decoded it -- not a bare photo, and not a broken image.
    stage = page.locator(".preview-stage--large img")
    stage.wait_for(state="visible")
    assert "/scene-preview?" in (stage.get_attribute("src") or "")
    page.wait_for_function(
        "img => img.complete && img.naturalWidth > 0", arg=stage.element_handle()
    )


def test_an_empty_pair_survives_a_reload(page: Any, workspace_root: Path) -> None:  # noqa: ANN401
    edit_listing(workspace_root, design={})
    _open(page)

    page.get_by_role("button", name="Unlink").click()
    _wait_for_design(page, workspace_root, {"on-light": None, "on-dark": None})

    page.reload()
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    assert page.get_by_role("button", name="Link", exact=True).is_visible()
    assert "Choose the design for light shirts" in _card(page, "For light shirts").inner_text()
    assert "Choose the design for dark shirts" in _card(page, "For dark shirts").inner_text()


def test_link_a_pair_of_two_files_and_choose_one(page: Any, workspace_root: Path) -> None:  # noqa: ANN401
    _designs(workspace_root)
    edit_listing(workspace_root, design={"on-light": DARK_INK, "on-dark": LIGHT_INK})
    _open(page)

    page.get_by_role("button", name="Link", exact=True).click()
    dialog = page.get_by_role("dialog", name="Which design should every shirt print?")
    confirm = dialog.get_by_role("button", name="Use one design")
    assert confirm.is_disabled()

    dialog.get_by_role("radio", name=re.compile("light-ink")).click()
    confirm.click()

    _wait_for_design(page, workspace_root, {"default": LIGHT_INK})
    assert page.get_by_role("button", name="Unlink").is_visible()


MOSS_SPECIAL = "designs/moss-special.png"


def _shown(page: Any, image: Any) -> bytes:  # noqa: ANN401
    """The picture ``image`` shows, once the browser has decoded it -- fetched
    again by its URL, so it can be compared with the render it should be."""
    page.wait_for_function("img => img.complete && img.naturalWidth > 0", arg=image)
    src = image.get_attribute("src")
    assert src is not None
    response = page.request.get(page.url.split("/listings/")[0] + src)
    assert response.ok, response.status
    return bytes(response.body())


def _stage_once_saved(page: Any, template: str, before: str) -> Any:  # noqa: ANN401
    """The large preview of ``template``, once its URL no longer carries the
    design signature ``before`` -- a save has landed and the picture is the
    newly saved listing's."""
    selector = f".preview-stage--large img[src*='template={template}']"
    page.wait_for_function(
        "([sel, before]) => { const img = document.querySelector(sel);"
        " return img !== null && !img.src.endsWith('v=' + before); }",
        arg=[selector, before],
    )
    return page.locator(selector).element_handle()


def _signature(page: Any) -> str:  # noqa: ANN401
    """The saved design's signature on the Variants stage's picture."""
    stage = page.locator(".preview-stage--large img")
    stage.wait_for(state="visible")
    return (stage.get_attribute("src") or "").rsplit("v=", 1)[1]


def test_give_moss_its_own_design_and_return_it_to_automatic(
    page: Any,  # noqa: ANN401
    workspace_root: Path,
) -> None:
    """Acceptance 4, and 5 for a colour's own design: Moss prints its own file
    on the Variants stage and on its layer of a two-colour Listing Images
    scene, then goes back to the design for all shirts."""
    with Image.open(workspace_root / HIKE) as hike:
        Image.new("RGBA", hike.size, (40, 200, 60, 255)).save(workspace_root / MOSS_SPECIAL)
    edit_listing(
        workspace_root,
        design={"default": HIKE},
        media=[{"template": "flat-lay-01", "colour": "moss"}, {"template": "colour-chart-01"}],
    )
    _open(page)
    before = _signature(page)

    page.get_by_role("button", name="Select different design for Moss").click()
    dialog = page.get_by_role("dialog", name="Design for Moss")
    dialog.get_by_role("button", name=re.compile("moss-special")).click()
    _wait_for_design(page, workspace_root, {"default": HIKE, "moss": MOSS_SPECIAL})

    row = page.locator(".color-row", has=page.get_by_text("moss", exact=True))
    assert row.get_by_text("own design").is_visible()
    shown = _shown(page, _stage_once_saved(page, "flat-lay-01", before))
    assert shown == expected_scene(workspace_root, "flat-lay-01", "moss", {"moss": MOSS_SPECIAL})
    own = _signature(page)

    page.get_by_text("Listing Images", exact=True).click()
    page.locator(".rtile img[alt*='colour-chart-01']").hover()
    shown = _shown(page, _stage_once_saved(page, "colour-chart-01", before))
    assert shown == expected_scene(
        workspace_root, "colour-chart-01", None, {"black": HIKE, "moss": MOSS_SPECIAL}
    )

    # The strip names Moss; pressing it previews Moss back on Variants.
    page.locator(".design-select__own").get_by_role("button", name="Moss").click()
    card = page.locator(".color-prints")
    assert "Back on automatic it would print take-a-hike" in card.inner_text()
    card.get_by_role("button", name="Use automatic design").click()
    _wait_for_design(page, workspace_root, {"default": HIKE})

    assert row.get_by_text("own design").count() == 0
    shown = _shown(page, _stage_once_saved(page, "flat-lay-01", own))
    assert shown == expected_scene(workspace_root, "flat-lay-01", "moss", {"moss": HIKE})

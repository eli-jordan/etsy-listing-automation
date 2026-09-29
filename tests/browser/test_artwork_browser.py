"""Browser test for light and dark base artwork (multi-artwork plan, PR 2):
unlink, pick both files, reload and see both; link a pair of two files and
choose one. Asserted on the `listing.yaml` the UI wrote and on pictures the
browser actually decoded, like the rest of this layer.

Acceptance 2 (switch to light/dark and pick both) and 3 (a partial pair
survives a reload).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.support.builders import edit_listing

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

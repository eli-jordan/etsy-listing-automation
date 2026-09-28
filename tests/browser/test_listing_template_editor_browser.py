"""Browser tests for the listing-template editor (batch plan PR 6; UI doc §2,
§3): the listing editor's shell over a listing template, the valid-only
``PUT`` (A36), the rename and create endpoints and the files they write,
together in a real browser.

* Switch every colour off -> *Not saved* and the tab badge, with
  ``template.yaml`` untouched -> switch one back on -> written.
* Navigating away while unsaved asks first.
* Clone -> name -> two independent listing templates on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from playwright.sync_api import expect

from etsy_listings.workspace.workspace import Workspace

from tests.support.batches import GARMENT_PROFILE, LISTING_TEMPLATE, a_listing_template
from tests.support.builders import edit_garment_profile

pytestmark = pytest.mark.browser

COLOURS = ["black", "blue-jean", "ivory", "moss"]


def _template_file(root: Path, name: str = LISTING_TEMPLATE) -> Path:
    return root / "listing-templates" / name / "template.yaml"


def _colours(root: Path, name: str = LISTING_TEMPLATE) -> list[str]:
    colours: list[str] = yaml.safe_load(_template_file(root, name).read_text("utf-8"))["colors"]
    return colours


def _a_classified_listing_template(root: Path) -> None:
    """The fixture template, with its garment's colours classified: an
    unclassified colour switched off leaves the Variants list, so there
    would be no switch left to turn back on."""
    a_listing_template(Workspace.discover(root_override=root))
    edit_garment_profile(root, GARMENT_PROFILE, colors=dict.fromkeys(COLOURS, "dark"))


def _open(page, name: str = LISTING_TEMPLATE) -> None:  # noqa: ANN001
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/listing-templates/{name}")
    page.get_by_text(f"listing-templates/{name}/template.yaml").wait_for()


def _switch_every_colour_off(page) -> None:  # noqa: ANN001
    for colour in COLOURS:
        switch = page.get_by_role("switch", name=colour)
        switch.click()
        expect(switch).to_have_attribute("aria-checked", "false")


def test_an_incomplete_listing_template_is_kept_off_disk_until_it_is_complete(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    _a_classified_listing_template(workspace_root)
    _open(page)
    # The preview row is the listing editor's design row, reworded (UI doc §3).
    assert page.get_by_text("Preview design: Grid / ruler target").is_visible()

    _switch_every_colour_off(page)

    page.get_by_text("Not saved — fix the highlighted field and it will be written").wait_for()
    assert page.get_by_text("Last complete version is kept until then").is_visible()
    assert page.locator(".seg-opt", has_text="Variants").locator(".tab-badge").is_visible()
    # Each switch before the last left a complete template, and was written;
    # the last one did not, so the file is the last complete version (A36).
    assert _colours(workspace_root) == ["moss"]

    page.get_by_role("switch", name="black").click()

    page.get_by_text(f"listing-templates/{LISTING_TEMPLATE}/template.yaml").wait_for()
    expect(page.locator(".issues")).to_have_count(0)
    assert _colours(workspace_root) == ["black"]


def test_leaving_with_an_unsaved_edit_asks_first(page, workspace_root: Path) -> None:  # noqa: ANN001
    _a_classified_listing_template(workspace_root)
    _open(page)
    _switch_every_colour_off(page)
    page.get_by_text("Not saved — fix the highlighted field and it will be written").wait_for()

    page.locator(".page-head__crumb", has_text="Listing templates").click()

    dialog = page.get_by_role("dialog", name="Leave without saving this listing template?")
    dialog.wait_for()
    dialog.get_by_role("button", name="Cancel").click()
    assert page.url.endswith(f"/listing-templates/{LISTING_TEMPLATE}")

    page.locator(".page-head__crumb", has_text="Listing templates").click()
    page.get_by_role("dialog").get_by_role("button", name="Leave").click()
    page.locator("article.bc-card", has_text=LISTING_TEMPLATE).wait_for()
    assert _colours(workspace_root) == ["moss"]


def test_clone_and_name_makes_two_independent_listing_templates(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    _a_classified_listing_template(workspace_root)
    base = page.url.rsplit("/", 1)[0]
    page.goto(f"{base}/listing-templates")

    page.get_by_role("link", name=f"Clone {LISTING_TEMPLATE}").click()
    name = page.get_by_label("Template name")
    name.wait_for()
    assert page.get_by_text("Not saved — name this template to save it").is_visible()
    name.fill("everyday-tee")
    name.press("Enter")
    page.wait_for_url("**/listing-templates/everyday-tee")
    page.get_by_text("listing-templates/everyday-tee/template.yaml").wait_for()

    # An edit to the clone reaches only the clone.
    switch = page.get_by_role("switch", name="moss")
    switch.click()
    expect(switch).to_have_attribute("aria-checked", "false")
    _eventually(page, lambda: _colours(workspace_root, "everyday-tee") == COLOURS[:3])

    assert _colours(workspace_root) == COLOURS
    for name in (LISTING_TEMPLATE, "everyday-tee"):
        own = workspace_root / "listing-templates" / name / "assets" / "shots" / "size-chart.png"
        assert own.is_file()


def _eventually(page, condition) -> None:  # noqa: ANN001
    """Wait out the autosave debounce for a file the browser writes."""
    for _ in range(100):
        if condition():
            return
        page.wait_for_timeout(100)
    assert condition()

"""Browser tests for finding templates by label in the Add media panel, on a
listing and on a listing template: the search box over the real template list, a
colour added through the filter reaching the file, and the filter coming back
from `sessionStorage` after a real reload. Vitest can only remount the component.

Labels go into the workspace copy, so the checked-in fixtures keep their hashes.
Skips cleanly when playwright or its chromium build is missing (`conftest.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from playwright.sync_api import expect

from etsy_listings.core.workspace.workspace import Workspace

from tests.support.batches import GARMENT_PROFILE, LISTING_TEMPLATE, a_listing_template
from tests.support.builders import edit_garment_profile, edit_listing
from tests.support.marigold import wait_until

pytestmark = pytest.mark.browser

LABELLED = "flat-lay-01"
OTHER = "colour-chart-01"
THREE_COLOURS = [
    {"template": LABELLED, "colour": colour} for colour in ("black", "blue-jean", "ivory")
]
MOSS = {"template": LABELLED, "colour": "moss"}


def _label_templates(root: Path) -> None:
    for template, label in ((LABELLED, "theme:christmas"), (OTHER, "theme:summer")):
        path = root / "mockup-templates" / template / "template.yaml"
        with path.open("a", encoding="utf-8") as file:
            file.write(f"labels: [{label}]\n")


def _media(path: Path) -> list[object]:
    media: list[object] = yaml.safe_load(path.read_text("utf-8"))["media"]
    return media


def _tab(page, name: str) -> None:
    page.locator(".tabs .seg-opt", has_text=name).click()


def _open_images(page) -> None:
    _tab(page, "Images")
    page.locator(".locator").wait_for(state="visible")


def _box(page):
    return page.get_by_role("combobox", name="Search templates")


def _result_line(page):
    return page.locator(".locator__result")


def _filter_is_intact(page) -> None:
    """The pill and the text are back, and the list obeys them."""
    expect(page.get_by_role("button", name="Remove theme:christmas")).to_be_visible()
    expect(_box(page)).to_have_value("flat")
    expect(_result_line(page)).to_have_text("1 of 2 templates")
    expect(page.locator(".loc-tmpl__name")).to_have_text([LABELLED])


def _add_moss_through_the_filter(page) -> None:
    expect(_result_line(page)).to_have_text("1 of 2 templates")
    page.locator(".loc-tmpl__head", has_text=LABELLED).click()
    page.locator(".locator").get_by_role("button", name="moss").click()


def _pricing_and_back_then_refresh(page) -> None:
    _tab(page, "Pricing")
    page.locator(".locator").wait_for(state="detached")
    _open_images(page)
    _filter_is_intact(page)

    page.reload()
    page.locator(".locator").wait_for(state="visible")
    _filter_is_intact(page)


def test_a_listings_filter_outlasts_pricing_and_a_refresh(page, workspace_root: Path) -> None:
    edit_listing(workspace_root, media=THREE_COLOURS)
    _label_templates(workspace_root)
    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    _open_images(page)
    expect(_result_line(page)).to_have_text("2 of 2 templates")
    expect(page.locator(".loc-tmpl", has_text=LABELLED)).to_contain_text("theme:christmas")

    _box(page).focus()
    page.keyboard.type("CHR")
    expect(_result_line(page)).to_have_text("0 of 2 templates")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    _add_moss_through_the_filter(page)
    listing = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    wait_until(lambda: MOSS in _media(listing), "the colour reaching listing.yaml")
    _box(page).fill("flat")

    _pricing_and_back_then_refresh(page)

    # View memory, not the document: only the colour reached the file.
    assert "theme:christmas" not in listing.read_text("utf-8")


def test_a_listing_templates_filter_outlasts_pricing_and_a_refresh(
    page, workspace_root: Path
) -> None:
    edit_listing(workspace_root, media=THREE_COLOURS)
    a_listing_template(Workspace.discover(root_override=workspace_root))
    edit_garment_profile(
        workspace_root,
        GARMENT_PROFILE,
        colors=dict.fromkeys(("black", "blue-jean", "ivory", "moss"), "dark"),
    )
    _label_templates(workspace_root)
    page.goto(page.url.rsplit("/", 1)[0] + f"/listing-templates/{LISTING_TEMPLATE}")
    _open_images(page)

    _box(page).click()
    # A click rather than the keyboard: the dropdown must sit over the list.
    page.get_by_role("option", name="theme:christmas").click()
    _add_moss_through_the_filter(page)
    template = workspace_root / "listing-templates" / LISTING_TEMPLATE / "template.yaml"
    wait_until(lambda: MOSS in _media(template), "the colour reaching template.yaml")
    _box(page).fill("flat")

    _pricing_and_back_then_refresh(page)


def test_switching_to_files_keeps_the_pill_and_clears_the_text(page, workspace_root: Path) -> None:
    _label_templates(workspace_root)
    page.goto(page.url.rsplit("/", 1)[0] + "/listings/take-a-hike")
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    _open_images(page)
    _box(page).click()
    page.get_by_role("option", name="theme:christmas").click()
    _box(page).fill("flat")

    page.get_by_role("button", name="Files", exact=True).click()
    expect(_box(page)).to_have_count(0)
    page.get_by_role("button", name="Mockup templates").click()

    expect(page.get_by_role("button", name="Remove theme:christmas")).to_be_visible()
    expect(_box(page)).to_have_value("")
    expect(_result_line(page)).to_have_text("1 of 2 templates")

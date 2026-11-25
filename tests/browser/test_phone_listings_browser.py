"""The lists and batch pages on a phone, driven with a finger: the Listings
list and its action sheet, the Dashboard's counts as shortcuts, and a batch
from New batch through staging to the summary, renamed with a tap.

The app is served with a ready AI provider and the in-memory Etsy market,
as ``test_batch_creation_browser`` serves it, so staging can create a batch
and the queue drafts its briefs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect

from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import ChainProvider, seed_prompts, seeded_market
from tests.support.batches import a_listing_template, png
from tests.support.clients import FakeClients
from tests.support.mobile import assert_mobile_page_fits, swipe

pytestmark = pytest.mark.browser


@pytest.fixture
def app_options(workspace_root: Path) -> dict[str, Any]:
    seed_prompts(workspace_root)
    provider = ChainProvider()
    return {
        "seo_provider_factory": lambda _workspace, _ai: [provider],
        "clients": FakeClients(etsy_market=seeded_market()).factories(),
    }


def _origin(page) -> str:
    return page.url.rstrip("/")


def test_listings_are_a_tappable_list(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    page.get_by_role("heading", name="Listings").wait_for(state="visible")

    # No table on a phone: one row per listing, and the filter is chips.
    expect(page.locator("table.listings")).to_have_count(0)
    rows = page.get_by_role("list", name="Listings").get_by_role("listitem")
    expect(rows).to_have_count(1)
    expect(page.get_by_role("radio", name=re.compile("^All"))).to_have_attribute(
        "aria-checked", "true"
    )
    assert_mobile_page_fits(page)

    # Search narrows the list; the whole row opens the listing.
    page.get_by_placeholder("Search listings…").fill("nothing-like-this")
    expect(rows).to_have_count(0)
    page.get_by_placeholder("Search listings…").fill("hike")
    rows.first.locator(".m-row__main").tap()
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    assert page.url.endswith("/listings/take-a-hike")


def test_a_rows_actions_are_a_bottom_sheet(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    more = page.get_by_role("button", name="More actions for take-a-hike")
    more.tap()
    sheet = page.get_by_role("dialog", name="take-a-hike", exact=True)
    action = sheet.get_by_role("button", name=re.compile("^(Delete|Mark for deletion)$"))
    # An action closes the sheet and goes through the usual confirm.
    action.tap()
    sheet.wait_for(state="detached")
    confirm = page.get_by_role("dialog", name=re.compile("^Are you sure"))
    confirm.get_by_role("button", name="Cancel").tap()
    confirm.wait_for(state="detached")

    # Cancel and a swipe down both dismiss it. (The swipe comes last: the
    # first tap after a CDP-dispatched swipe produces no click.)
    more.tap()
    sheet.get_by_role("button", name="Cancel").tap()
    sheet.wait_for(state="detached")
    more.tap()
    sheet.wait_for(state="visible")
    page.wait_for_function("() => document.getAnimations().length === 0")
    grabber = page.locator(".sheet-grabber").bounding_box()
    x = grabber["x"] + grabber["width"] / 2
    y = grabber["y"] + grabber["height"] / 2
    swipe(page, (x, y), (x, y + 260))
    sheet.wait_for(state="detached")
    expect(page.get_by_role("list", name="Listings").get_by_role("listitem")).to_have_count(1)


def _tall_page(page) -> None:
    """Room to scroll: the fixture has one listing, so the page is short."""
    page.evaluate(
        """() => {
            const spacer = document.createElement('div');
            spacer.style.height = '2000px';
            document.querySelector('main').append(spacer);
        }"""
    )


def test_a_sheet_is_modal_and_keeps_the_page_still(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    more = page.get_by_role("button", name="More actions for take-a-hike")
    more.wait_for(state="visible")
    _tall_page(page)
    page.evaluate("window.scrollTo(0, 120)")
    page.wait_for_function("() => window.scrollY === 120")
    more.click()
    sheet = page.get_by_role("dialog", name="take-a-hike", exact=True)
    sheet.wait_for(state="visible")
    page.wait_for_function("() => document.getAnimations().length === 0")

    # A drag on the dimmed page behind it does not scroll that page.
    swipe(page, (195, 120), (195, 20), steps=6)
    page.wait_for_timeout(300)
    assert page.evaluate("window.scrollY") == 120

    # Focus is in the sheet, and Tab keeps it there.
    inside = "() => document.querySelector('[role=dialog]').contains(document.activeElement)"
    assert page.evaluate(inside)
    for _ in range(8):
        page.keyboard.press("Tab")
        assert page.evaluate(inside)

    # Escape closes it, hands focus back to the ⋯ and leaves the page where it was.
    page.keyboard.press("Escape")
    sheet.wait_for(state="detached")
    expect(more).to_be_focused()
    assert page.evaluate("window.scrollY") == 120


def test_a_sheet_drags_away_by_its_title(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    page.get_by_role("button", name="More actions for take-a-hike").tap()
    sheet = page.get_by_role("dialog", name="take-a-hike", exact=True)
    sheet.wait_for(state="visible")
    page.wait_for_function("() => document.getAnimations().length === 0")
    title = page.locator(".phone-sheet__title").bounding_box()
    x, y = title["x"] + 20, title["y"] + title["height"] / 2
    swipe(page, (x, y), (x, y + 250))
    sheet.wait_for(state="detached")


def test_back_closes_a_sheet_and_not_the_page(phone_page) -> None:
    page = phone_page
    page.get_by_role("navigation").get_by_role("link", name="Listings", exact=True).tap()
    page.wait_for_url("**/listings")
    more = page.get_by_role("button", name="More actions for take-a-hike")
    sheet = page.get_by_role("dialog", name="take-a-hike", exact=True)

    more.tap()
    sheet.wait_for(state="visible")
    page.go_back()
    sheet.wait_for(state="detached")
    assert page.url.endswith("/listings")

    # A sheet that hands over to a confirm: Back closes the confirm, and
    # the next Back still leaves in one press.
    more.tap()
    sheet.get_by_role("button", name=re.compile("^(Delete|Mark for deletion)$")).tap()
    confirm = page.get_by_role("dialog", name=re.compile("^Are you sure"))
    confirm.wait_for(state="visible")
    page.go_back()
    confirm.wait_for(state="detached")
    assert page.url.endswith("/listings")
    page.go_back()
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")

    # Closed some other way, its history entry goes too: one Back leaves.
    page.get_by_role("navigation").get_by_role("link", name="Listings", exact=True).tap()
    page.wait_for_url("**/listings")
    more.tap()
    sheet.get_by_role("button", name="Cancel").tap()
    sheet.wait_for(state="detached")
    page.wait_for_timeout(200)
    assert page.url.endswith("/listings")
    page.go_back()
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")


def test_new_listing_floats_above_the_tab_bar(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    fab = page.get_by_role("button", name="New listing", exact=True)
    fab.wait_for(state="visible")
    bar = page.locator(".sidebar").bounding_box()
    box = fab.bounding_box()
    assert box["y"] + box["height"] < bar["y"]
    assert box["width"] >= 44
    fab.tap()
    page.wait_for_url("**/listings/new")


def test_a_dashboard_count_opens_the_listings_it_counts(phone_page) -> None:
    page = phone_page
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")
    card = page.locator("a.stat-card", has_text="Draft")
    card.tap()
    page.wait_for_url(re.compile(r"/listings\?status=draft$"))
    expect(page.get_by_role("radio", name=re.compile("^Draft"))).to_have_attribute(
        "aria-checked", "true"
    )
    # The Listings tab drops the filter again.
    page.get_by_role("navigation").get_by_role("link", name="Listings", exact=True).tap()
    expect(page.get_by_role("radio", name=re.compile("^All"))).to_have_attribute(
        "aria-checked", "true"
    )
    assert_mobile_page_fits(page)


def test_a_batch_from_choosing_files_to_a_renamed_reviewed_summary(
    phone_page, workspace_root: Path
) -> None:
    page = phone_page
    a_listing_template(Workspace.discover(root_override=workspace_root))
    page.goto(f"{_origin(page)}/batches/new?template=heavyweight-tee")

    # A phone picks files rather than dropping them.
    page.get_by_text("Choose a ZIP or PNGs").wait_for(state="visible")
    expect(page.get_by_role("button", name="Choose files", exact=True)).to_be_visible()
    assert_mobile_page_fits(page)
    page.get_by_label("Design files").set_input_files(
        [
            {"name": "lake-loop.png", "mimeType": "image/png", "buffer": png(4)},
            {"name": "★★★.png", "mimeType": "image/png", "buffer": png(5)},
        ]
    )

    # Staging: one card per design, its name field the card's full width.
    page.get_by_role("heading", name="Review 2 designs").wait_for()
    cards = page.get_by_role("list", name="Staged designs").get_by_role("listitem")
    expect(cards).to_have_count(2)
    assert_mobile_page_fits(page)
    name = page.get_by_label("Listing name for ★★★.png")
    card_box = cards.filter(has=name).bounding_box()
    assert name.bounding_box()["width"] > card_box["width"] * 0.8
    name.fill("summit-coffee")
    name.press("Enter")
    page.get_by_text("Briefs are drafted automatically.", exact=False).wait_for()
    page.get_by_role("button", name="Create 2 listings").tap()

    # The summary: cards with labelled states, a tap renames.
    summary = page.get_by_role("list", name="Listings in this batch")
    expect(summary.get_by_role("listitem")).to_have_count(2)
    expect(page.get_by_text("Brief ready")).to_have_count(2)
    page.get_by_text("Tap the name to rename it").wait_for(state="visible")
    assert_mobile_page_fits(page)
    page.locator("h1.page-head__title").tap()
    label = page.get_by_label("Batch label")
    label.fill("Trail runs")
    label.press("Enter")
    expect(page.get_by_role("heading", name="Trail runs")).to_be_visible()

    card = summary.get_by_role("listitem").filter(has_text="lake-loop")
    card.get_by_role("button", name="Mark reviewed").tap()
    expect(card.get_by_role("button", name="Reviewed")).to_be_visible()
    expect(page.locator(".bc-counts")).to_contain_text("1 of 2 reviewed")

    # Recent batches is a list whose rows open the batch.
    page.goto(f"{_origin(page).split('/batches', 1)[0]}/listing-templates")
    batches = page.get_by_role("list", name="Recent batches")
    batches.get_by_role("link", name=re.compile("Trail runs")).tap()
    page.get_by_role("heading", name="Trail runs").wait_for(state="visible")

    # A card's head opens its listing in the editor.
    summary.get_by_role("link", name=re.compile("summit-coffee")).tap()
    page.wait_for_url(re.compile(r"/listings/summit-coffee\?batch="))

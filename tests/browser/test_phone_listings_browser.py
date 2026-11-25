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


def _assert_over_the_title(page) -> None:
    """The page head's back link sits on a line of its own above the title."""
    crumb = page.locator(".page-head__crumb").bounding_box()
    title = page.locator(".page-head__title").first.bounding_box()
    assert crumb["y"] + crumb["height"] <= title["y"], (crumb, title)
    # The "/" separator, which only breaks the line, is not drawn.
    expect(page.locator(".page-head__sep").first).not_to_be_visible()


def _hit(page, x: float, y: float) -> str:
    """The aria-label or text of the button a tap at (x, y) lands on."""
    return page.evaluate(
        """([x, y]) => {
            const button = document.elementFromPoint(x, y)?.closest('button');
            return button ? (button.getAttribute('aria-label') || button.textContent.trim()) : '';
        }""",
        [x, y],
    )


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


def test_new_listing_steps_aside_while_the_list_scrolls_down(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    fab = page.get_by_role("button", name="New listing", exact=True)
    fab.wait_for(state="visible")
    # One fixture listing does not scroll: a spacer over the list makes the
    # page as long as a real shop's.
    page.evaluate(
        """() => {
            const spacer = document.createElement('div');
            spacer.style.height = '2400px';
            document.querySelector('.m-list').before(spacer);
        }"""
    )

    swipe(page, (200, 700), (200, 250))
    expect(fab).to_have_class(re.compile("m-fab--hidden"))
    page.wait_for_function("() => document.getAnimations().length === 0")
    box = fab.bounding_box()
    assert _hit(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2) != "New listing"

    swipe(page, (200, 300), (200, 500))
    expect(fab).not_to_have_class(re.compile("m-fab--hidden"))

    # Back at the list's end, it leaves the last row's ⋯ clear.
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    expect(fab).to_have_class(re.compile("m-fab--hidden"))
    page.evaluate("window.scrollBy(0, -20)")
    expect(fab).not_to_have_class(re.compile("m-fab--hidden"))
    page.wait_for_function("() => document.getAnimations().length === 0")
    more = page.get_by_role("button", name="More actions for take-a-hike").bounding_box()
    centre = (more["x"] + more["width"] / 2, more["y"] + more["height"] / 2)
    assert _hit(page, *centre) == "More actions for take-a-hike"
    assert more["y"] + more["height"] <= fab.bounding_box()["y"]


def test_status_chips_have_finger_sized_hit_areas(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    box = page.get_by_role("radio", name=re.compile("^All")).bounding_box()
    # 44px tall to a finger, though the pill is drawn smaller.
    reach = (44 - box["height"]) / 2
    for y in (box["y"] - reach + 1, box["y"] + box["height"] + reach - 1):
        assert _hit(page, box["x"] + box["width"] / 2, y).startswith("All"), y


def test_a_sheets_actions_are_full_width_rows(phone_page) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings")
    radii = page.locator(".m-row__main").evaluate_all(
        "(els) => els.map((el) => getComputedStyle(el).borderRadius)"
    )
    page.get_by_role("button", name="More actions for take-a-hike").tap()
    radii += page.locator(".m-sheet__actions .m-sheet__action").evaluate_all(
        "(els) => els.map((el) => getComputedStyle(el).borderRadius)"
    )
    assert set(radii) == {"0px"}, radii


def test_candidate_changes_open_from_their_counts_without_a_plan(phone_page) -> None:
    page = phone_page
    posts: list[str] = []

    def record(route) -> None:
        if route.request.method == "POST":
            posts.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    page.route("**/api/runs**", record)
    page.goto(f"{_origin(page)}/listings")
    counts = page.get_by_role("button", name=re.compile("^Candidate changes: 1 to add"))
    counts.tap()
    sheet = page.get_by_role("dialog", name="Candidate changes")
    expect(sheet).to_contain_text("take-a-hike")
    assert counts.bounding_box()["height"] >= 44
    done = sheet.get_by_role("button", name="Done")
    assert done.bounding_box()["height"] >= 44
    done.tap()
    sheet.wait_for(state="detached")
    assert posts == []

    # Deploy changes itself still starts the plan.
    page.get_by_role("button", name="Deploy changes", exact=True).tap()
    page.get_by_text("could not start a workspace plan").wait_for()
    assert len(posts) == 1, posts
    assert posts[0].endswith("/api/runs"), posts


def test_back_from_a_listing_keeps_the_filter_and_the_search(phone_page) -> None:
    page = phone_page
    page.get_by_role("heading", name="Dashboard").wait_for(state="visible")
    page.locator("a.stat-card", has_text="Draft").tap()
    page.wait_for_url(re.compile(r"/listings\?status=draft$"))
    rows = page.get_by_role("list", name="Listings").get_by_role("listitem")

    page.get_by_role("radio", name=re.compile("^All")).tap()
    page.get_by_placeholder("Search listings…").fill("hike")
    page.wait_for_url(re.compile(r"/listings\?q=hike$"))
    rows.first.locator(".m-row__main").tap()
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    page.go_back()
    expect(page.get_by_role("radio", name=re.compile("^All"))).to_have_attribute(
        "aria-checked", "true"
    )
    expect(page.get_by_placeholder("Search listings…")).to_have_value("hike")

    # A chip is kept the same way, and the Listings tab drops it.
    page.get_by_role("radio", name=re.compile("^Draft")).tap()
    page.wait_for_url(re.compile(r"status=draft"))
    rows.first.locator(".m-row__main").tap()
    page.get_by_role("heading", name="take-a-hike").wait_for(state="visible")
    page.go_back()
    expect(page.get_by_role("radio", name=re.compile("^Draft"))).to_have_attribute(
        "aria-checked", "true"
    )
    page.get_by_role("navigation").get_by_role("link", name="Listings", exact=True).tap()
    expect(page.get_by_role("radio", name=re.compile("^All"))).to_have_attribute(
        "aria-checked", "true"
    )


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
    # One way back, over the title, as on every phone page.
    crumbs = page.locator(".page-head__crumb")
    expect(crumbs).to_have_count(1)
    expect(crumbs).to_have_text("New batch")
    _assert_over_the_title(page)
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
    _assert_over_the_title(page)
    page.locator("h1.page-head__title").tap()
    label = page.get_by_label("Batch label")
    label.fill("Trail runs")
    label.press("Enter")
    expect(page.get_by_role("heading", name="Trail runs")).to_be_visible()

    card = summary.get_by_role("listitem").filter(has_text="lake-loop")
    # Reviewed is a labelled switch, so a tap that clears it is no surprise.
    reviewed = card.get_by_role("switch", name="Reviewed")
    expect(reviewed).to_have_attribute("aria-checked", "false")
    reviewed.tap()
    expect(reviewed).to_have_attribute("aria-checked", "true")
    expect(page.locator(".bc-counts")).to_contain_text("1 of 2 reviewed")
    assert reviewed.bounding_box()["height"] >= 44

    # Recent batches is a list whose rows open the batch.
    page.goto(f"{_origin(page).split('/batches', 1)[0]}/listing-templates")
    batches = page.get_by_role("list", name="Recent batches")
    batches.get_by_role("link", name=re.compile("Trail runs")).tap()
    page.get_by_role("heading", name="Trail runs").wait_for(state="visible")

    # A card's head opens its listing in the editor.
    summary.get_by_role("link", name=re.compile("summit-coffee")).tap()
    page.wait_for_url(re.compile(r"/listings/summit-coffee\?batch="))

"""Deploy, Deploy reviewed and Admin on a phone, driven with a finger.

The real app serves the fixture workspace with fake vendor clients (the way
``test_deploy_view.py`` does), so a plan runs with no credentials. The
fixture's plan has no Etsy listing, so the states that need one -- drift,
price changes, a workspace review -- are served from canned run events
through ``page.route``, shaped like the wire format the runs API streams.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest

from etsy_listings.core.application.backup_coordinator import BackupEnvironment
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.mobile import assert_mobile_page_fits, swipe

pytestmark = pytest.mark.browser

PASSWORD = "correct horse battery staple"
RESTIC_TIMEOUT_MS = 120_000


def _context_factory(workspace: Workspace, on_event: EventSink | None) -> RunContext:
    kwargs = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=workspace,
        catalog=FakeCatalogClient([], {}, {}),
        printify=None,
        etsy=None,
        **kwargs,
    )


@pytest.fixture
def app_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake vendors for plans, and backup state under ``tmp_path``. The
    restic test finds restic through ``ETSY_LISTINGS_RESTIC_BINARY``."""
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    return {
        "context_factory": _context_factory,
        "backup": BackupEnvironment(home=tmp_path / "home"),
    }


@pytest.fixture
def expect(browser_type):
    from playwright.sync_api import expect as playwright_expect

    return playwright_expect


def _origin(page) -> str:
    return page.url.rstrip("/")


def _tab_bar_top(page) -> float:
    return page.locator(".sidebar").bounding_box()["y"]


# -- canned runs --------------------------------------------------------------


def _stage(stage: str, *, changes=None, snapshot=None, drift=None, work=True, group=None):
    outcome = (
        {"type": "work", "reason": "changed", "changes": changes or [], "actions": []}
        if work
        else {"type": "idle"}
    )
    return {
        "outcome": outcome,
        "drift": drift or [],
        "group": group,
        "stage": stage,
        "snapshot": snapshot,
    }


def _plan(name: str) -> dict[str, Any]:
    sizes = ["S", "M", "L", "XL", "2XL", "3XL"]
    live = {
        "title": f"{name} T-Shirt, Hiking Shirt, Mountain Tee",
        "description": "A trail tee.\n\nWash cold.",
        "tags": ["hiking shirt", "mountain tee"],
        "materials": ["cotton"],
        "shop_section": None,
        "shipping_profile": None,
    }
    desired = {
        **live,
        "title": f"{name} Shirt, Comfort Colors Hiking Tee, Mountain Lover Gift",
        "tags": ["hiking shirt", "trail shirt"],
    }
    return {
        "listing": name,
        "is_live": True,
        "etsy_listing_id": 1698234512,
        "stage_plans": [
            _stage("render"),
            _stage(
                "printify_product",
                snapshot={
                    "live": [{"size": s, "colour": "black", "price": "349 NOK"} for s in sizes],
                    "desired": [{"size": s, "colour": "black", "price": "379 NOK"} for s in sizes],
                },
                changes=[
                    {
                        "kind": "price",
                        "size": s,
                        "before": "349 NOK",
                        "after": "379 NOK",
                        "color": "black",
                    }
                    for s in sizes
                ],
            ),
            _stage("publish", work=False),
            _stage(
                "etsy_listing",
                snapshot={"live": live, "desired": desired},
                changes=[
                    {
                        "kind": "field",
                        "path": "title",
                        "before": live["title"],
                        "after": desired["title"],
                    }
                ],
                drift=[
                    {
                        "path": "title",
                        "last_applied": live["title"],
                        "live": f"{name} Tee - Hiking Shirt for Mountain Lovers",
                    }
                ],
            ),
            _stage(
                "etsy_media", work=False, group="etsy_media", snapshot={"live": [], "desired": []}
            ),
        ],
    }


def _route_run(
    page, run_id: str, scope: str, names: list[str], failed: dict[str, str] | None = None
) -> None:
    """Serve one finished plan run for ``names`` from the runs API, with the
    listings in ``failed`` failing to plan with that message."""
    ids = itertools.count(1)
    events: list[dict[str, Any]] = [
        {"id": next(ids), "type": "phase", "phase": "queued"},
        {"id": next(ids), "type": "phase", "phase": "planning"},
    ]
    for name, message in (failed or {}).items():
        events.append(
            {"id": next(ids), "type": "listing_failed", "listing": name, "message": message}
        )
    for name in names:
        plan = _plan(name)
        events += [
            {"id": next(ids), "type": "stage_planned", "listing": name, "stage_plan": stage}
            for stage in plan["stage_plans"]
        ]
        events.append(
            {
                "id": next(ids),
                "type": "listing_planned",
                "listing": name,
                "plan": plan,
                "fingerprint": f"fp-{name}",
            }
        )
    events.append({"id": next(ids), "type": "phase", "phase": "ready"})
    summary = {
        "id": run_id,
        "scope": scope,
        "batch_id": None,
        "listings": names + list(failed or {}),
        "seen": False,
        "reviewed_run_id": None,
        "created_at": "2026-11-24T10:00:00Z",
        "waiting_for_backup": False,
        "kind": "plan",
        "phase": "ready",
    }

    def handle(route) -> None:
        url = route.request.url
        if url.endswith("/events"):
            route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body="")
        elif url.endswith("/seen"):
            route.fulfill(status=204, body="")
        elif f"/api/runs/{run_id}" in url:
            route.fulfill(json={**summary, "events": events})
        elif "/api/runs?" in url:
            route.fulfill(json=[summary])
        else:
            route.continue_()

    page.route("**/api/runs**", handle)


# -- Deploy -------------------------------------------------------------------


def test_deploy_reads_as_a_back_link_and_keeps_apply_on_the_tab_bar(phone_page, expect) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/listings/take-a-hike/deploy")
    page.get_by_role("heading", name="Deploy").wait_for(state="visible")

    # One back link named for where it goes, not a button and two crumbs.
    back = page.get_by_role("button", name="take-a-hike", exact=True)
    expect(back).to_be_visible()
    expect(page.get_by_role("button", name="← Back")).to_have_count(0)

    apply_button = page.get_by_role("button", name="Apply", exact=True)
    expect(apply_button).to_be_enabled(timeout=60_000)
    assert_mobile_page_fits(page)

    # The page is taller than the screen, yet Apply sits on the tab bar.
    assert page.evaluate("document.documentElement.scrollHeight") > page.viewport_size["height"]
    foot = page.locator(".dv-foot").bounding_box()
    assert foot["y"] + foot["height"] == pytest.approx(_tab_bar_top(page), abs=1)

    apply_button.tap()
    expect(page.get_by_text("Deployed.")).to_be_visible(timeout=60_000)
    assert_mobile_page_fits(page)
    page.get_by_role("button", name="take-a-hike", exact=True).tap()
    page.wait_for_url("**/listings/take-a-hike")


def test_a_drifted_priced_plan_fits_and_labels_each_side(phone_page, expect) -> None:
    page = phone_page
    _route_run(page, "r1", "listings", ["take-a-hike"])
    page.goto(f"{_origin(page)}/listings/take-a-hike/deploy")
    expect(page.get_by_role("button", name="Apply", exact=True)).to_be_enabled()

    # Every column of the price table is on screen, with no sideways scroll.
    table = page.locator(".dv-prices table")
    table.scroll_into_view_if_needed()
    box = table.bounding_box()
    assert box["x"] >= 0, box
    assert box["x"] + box["width"] <= page.viewport_size["width"], box
    expect(table.get_by_role("columnheader", name="Difference")).to_be_in_viewport()
    assert_mobile_page_fits(page)

    # A stacked pair says which side is which.
    labels = page.locator(".dv-compare .dv-row--drift .dv-block__label").evaluate_all(
        "(els) => els.map((el) => getComputedStyle(el, '::before').content)"
    )
    assert labels[:2] == ['"Now"', '"After"'], labels

    page.get_by_role("button", name="Compare Title").tap()
    expect(page.get_by_role("region", name="Title compared with this plan")).to_be_visible()
    assert_mobile_page_fits(page)


# -- Deploy reviewed ----------------------------------------------------------


def test_the_listing_drawer_is_a_bottom_sheet(phone_page, expect) -> None:
    page = phone_page
    _route_run(page, "w1", "workspace", ["take-a-hike", "mushroom-club-tee", "fern-gully"])
    page.goto(f"{_origin(page)}/listings/deploy/w1")
    page.get_by_role("heading", name="Review all changes").wait_for(state="visible")
    assert_mobile_page_fits(page)
    # Back reads as every phone page's: the parent's name over the title.
    back = page.get_by_role("button", name="Listings", exact=True)
    expect(back).to_be_visible()
    expect(page.get_by_role("button", name="← Back to listings")).to_have_count(0)
    title = page.get_by_role("heading", name="Review all changes").bounding_box()
    assert back.bounding_box()["y"] + back.bounding_box()["height"] <= title["y"]

    page.get_by_text("mushroom-club-tee", exact=True).first.tap()
    dialog = page.locator("dialog.batch-drawer-dialog")
    expect(dialog).to_have_js_property("open", True)
    page.wait_for_timeout(400)
    panel = page.locator(".batch-drawer-panel")
    body = page.locator(".batch-drawer__body")

    # The body scrolls under a finger without moving the sheet.
    resting = panel.bounding_box()
    top = body.bounding_box()["y"]
    swipe(page, (200, top + 320), (200, top + 80))
    page.wait_for_timeout(400)
    assert body.evaluate("(el) => el.scrollTop") > 0
    assert panel.bounding_box()["y"] == pytest.approx(resting["y"], abs=1)

    # Up on the header grows it; down sends it away.
    head = page.locator(".batch-drawer__head").bounding_box()
    swipe(page, (120, head["y"] + 30), (120, head["y"] - 200))
    page.wait_for_timeout(400)
    assert panel.bounding_box()["height"] > resting["height"] + 50

    head = page.locator(".batch-drawer__head").bounding_box()
    swipe(page, (120, head["y"] + 30), (120, head["y"] + 330))
    expect(dialog).to_have_js_property("open", False)


def test_the_listing_drawer_fits_a_long_unbroken_summary(phone_page, expect) -> None:
    page = phone_page
    # No hyphen or space: nothing in it lets a line break.
    path = "C:/Users/someone/" + "very_long_folder_name_" * 6 + "workspace/.env"
    failed = {"fern-gully": f"Put it in {path}"}
    _route_run(page, "w2", "workspace", ["take-a-hike"], failed=failed)
    page.goto(f"{_origin(page)}/listings/deploy/w2")
    page.get_by_role("heading", name="Review all changes").wait_for(state="visible")

    page.get_by_text("fern-gully", exact=True).first.tap()
    dialog = page.locator("dialog.batch-drawer-dialog")
    expect(dialog).to_have_js_property("open", True)
    page.wait_for_timeout(400)
    # The path wraps inside the sheet rather than pushing it off the left.
    assert dialog.evaluate("(el) => el.scrollLeft") == 0
    panel = page.locator(".batch-drawer-panel").bounding_box()
    assert panel["x"] == pytest.approx(0, abs=1)
    head = page.locator(".batch-drawer__head").bounding_box()
    assert head["x"] + head["width"] <= page.viewport_size["width"] + 1
    close = page.locator(".batch-drawer__head").get_by_role("button", name="Close")
    expect(close).to_be_in_viewport()


def test_a_grown_listing_drawer_fits_the_phone_turned_sideways(phone_page, expect) -> None:
    page = phone_page
    _route_run(page, "w3", "workspace", ["take-a-hike", "fern-gully"])
    page.goto(f"{_origin(page)}/listings/deploy/w3")
    page.get_by_role("heading", name="Review all changes").wait_for(state="visible")
    page.get_by_text("fern-gully", exact=True).first.tap()
    dialog = page.locator("dialog.batch-drawer-dialog")
    expect(dialog).to_have_js_property("open", True)
    page.wait_for_timeout(400)

    # The handle expands it to nearly the full height of the upright phone.
    page.locator(".batch-drawer__handle").tap()
    page.wait_for_timeout(400)
    assert page.locator(".batch-drawer-panel").bounding_box()["height"] > 700

    page.set_viewport_size({"width": 844, "height": 390})
    page.wait_for_timeout(500)
    panel = page.locator(".batch-drawer-panel").bounding_box()
    assert panel["y"] >= 0, panel
    assert panel["y"] + panel["height"] <= 390 + 1, panel
    close = page.locator(".batch-drawer__head").get_by_role("button", name="Close")
    expect(close).to_be_in_viewport()


# -- Admin --------------------------------------------------------------------


def test_admin_sections_are_chips_that_a_swipe_walks_through(phone_page, expect) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/admin")
    page.get_by_test_id("connection-etsy").wait_for(state="visible")
    assert_mobile_page_fits(page)

    chips = page.get_by_role("navigation", name="Admin sections")
    expect(page.locator(".adm-sections")).to_have_count(0)
    # Settings start on the first screen, under one row of chips.
    assert chips.bounding_box()["height"] < 70
    expect(page.get_by_role("heading", name="Connected shops")).to_be_in_viewport()

    chips.get_by_role("link", name="Template rendering").tap()
    page.wait_for_url("**/admin?section=rendering")
    page.wait_for_timeout(500)
    expect(chips.get_by_role("link", name="Template rendering")).to_be_in_viewport(ratio=1)

    # A drag across a slider moves the slider, not the section.
    slider = page.get_by_role("slider").first
    box = slider.bounding_box()
    swipe(page, (box["x"] + 20, box["y"] + box["height"] / 2), (box["x"] + 200, box["y"] + 10))
    page.wait_for_timeout(300)
    assert "section=rendering" in page.url

    content = page.locator(".adm-body > div").last
    middle = content.bounding_box()["y"] + 60
    swipe(page, (330, middle), (60, middle))
    page.wait_for_url("**/admin?section=backup")
    # The new section slides in from the right; the next swipe starts where
    # it comes to rest.
    page.wait_for_timeout(300)
    swipe(page, (60, middle), (330, middle))
    page.wait_for_url("**/admin?section=rendering")
    expect(chips.get_by_role("link", name="Template rendering")).to_have_attribute(
        "aria-current", "page"
    )

    # Off the end there is nowhere to go.
    page.goto(f"{_origin(page)}/admin")
    page.get_by_test_id("connection-etsy").wait_for(state="visible")
    swipe(page, (60, 400), (330, 400))
    page.wait_for_timeout(300)
    assert page.url.endswith("/admin")


def _hit_area(page, locator) -> dict[str, float]:
    """The box a finger can hit: where ``elementFromPoint`` still lands on
    ``locator`` (its pseudo-elements count), probed out from its centre."""
    return locator.evaluate(
        """(el) => {
            const box = el.getBoundingClientRect();
            const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
            const on = (x, y) => el.contains(document.elementFromPoint(x, y));
            let w = 0, h = 0;
            while (w < 60 && on(cx - w - 1, cy) && on(cx + w + 1, cy)) w += 1;
            while (h < 60 && on(cx, cy - h - 1) && on(cx, cy + h + 1)) h += 1;
            return {width: 2 * w + 1, height: 2 * h + 1};
        }"""
    )


def test_a_failed_shop_save_shows_on_screen_with_retry(phone_page, expect) -> None:
    page = phone_page

    def fail(route) -> None:
        if route.request.method == "PATCH":
            route.abort()
        else:
            route.continue_()

    page.route("**/api/admin/shop", fail)
    page.goto(f"{_origin(page)}/admin?section=defaults")
    renewal = page.get_by_role("combobox", name="Renewal")
    # The shop and its lookups load first; a reload would drop the edit.
    page.wait_for_load_state("networkidle")
    renewal.scroll_into_view_if_needed()
    options = renewal.evaluate(
        "(s) => [...s.options].map((o) => o.value).filter((v) => v !== s.value)"
    )
    # A field saves when it loses focus.
    renewal.focus()
    renewal.select_option(options[0])
    renewal.evaluate("(el) => el.blur()")

    # The page head has scrolled away under the chips; the toast has not.
    toast = page.locator(".adm-save-toast")
    retry = toast.get_by_role("button", name="Retry save")
    expect(retry).to_be_in_viewport(ratio=1)
    assert toast.bounding_box()["y"] + toast.bounding_box()["height"] <= _tab_bar_top(page)
    expect(page.locator(".page-head").get_by_role("button", name="Retry save")).to_have_count(0)

    page.unroute("**/api/admin/shop")
    retry.tap()
    expect(toast.get_by_role("status")).to_have_text("Saved")
    expect(toast.get_by_role("status")).to_have_text("", timeout=5_000)


def test_info_cards_fit_the_phone_and_close(phone_page, expect) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/admin?section=defaults")
    button = page.get_by_role("button", name="About Renewal")
    button.scroll_into_view_if_needed()
    area = _hit_area(page, button)
    assert area["width"] >= 43, area
    assert area["height"] >= 43, area

    # A tap just beside the 22px (i) opens it.
    box = button.bounding_box()
    page.touchscreen.tap(box["x"] + box["width"] + 8, box["y"] + box["height"] / 2)
    card = page.get_by_role("note", name="Renewal")
    expect(card).to_be_visible()
    card_box = card.bounding_box()
    width = page.viewport_size["width"]
    assert card_box["x"] >= 0, card_box
    assert card_box["x"] + card_box["width"] <= width, card_box
    assert card_box["y"] >= box["y"] + box["height"], (card_box, box)
    assert_mobile_page_fits(page)

    card.get_by_role("button", name="Close Renewal").tap()
    expect(card).to_have_count(0)


def test_admin_controls_have_finger_sized_hit_areas(phone_page, expect) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/admin?section=ai")
    page.locator(".b-chain > li .b-step__name").first.wait_for(state="visible")
    for locator in (
        page.locator(".adm-reorder__btn").first,
        page.locator(".sp-num").first,
        page.get_by_role("separator").first,
    ):
        locator.scroll_into_view_if_needed()
        area = _hit_area(page, locator)
        assert area["width"] >= 43, (locator, area)
        assert area["height"] >= 36, (locator, area)


def test_dragging_a_scoring_divider_stays_in_the_ai_section(phone_page, expect) -> None:
    page = phone_page
    patches: list[str] = []

    def hold(route) -> None:
        if route.request.method == "PATCH":
            patches.append(route.request.url)
        route.fallback()

    page.route("**/api/**", hold)
    page.goto(f"{_origin(page)}/admin?section=ai")
    divider = page.get_by_role("separator").first
    divider.scroll_into_view_if_needed()
    box = divider.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    swipe(page, (x, y), (x + 80, y))
    page.wait_for_timeout(500)
    # The divider moved the weights; the section stayed where it was.
    assert "section=ai" in page.url
    expect(
        page.get_by_role("navigation", name="Admin sections").get_by_role("link", name="AI")
    ).to_have_attribute("aria-current", "page")


def test_ai_providers_reorder_with_arrows_on_a_phone(phone_page, expect) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/admin?section=ai")
    chain = page.locator(".b-chain > li .b-step__name")
    chain.first.wait_for(state="visible")
    expect(page.get_by_text("Tap a number to turn it off")).to_be_visible()
    names = chain.all_inner_texts()

    page.get_by_role("button", name=f"Move {names[1]} up").tap()
    expect(chain.first).to_have_text(names[1])
    expect(page.get_by_role("button", name=f"Move {names[1]} up")).to_be_disabled()
    assert_mobile_page_fits(page)


def test_an_admin_alarm_dialog_is_a_sheet_a_swipe_dismisses(phone_page, expect) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/admin")
    page.get_by_role("button", name="Change currency…").tap()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    page.wait_for_function("() => document.getAnimations().length === 0")

    box = dialog.bounding_box()
    viewport = page.viewport_size
    assert box["y"] + box["height"] == pytest.approx(viewport["height"], abs=1)
    assert box["width"] == pytest.approx(viewport["width"], abs=1)

    grabber = page.locator(".sa-modal .sheet-grabber").bounding_box()
    x = grabber["x"] + grabber["width"] / 2
    swipe(page, (x, grabber["y"] + 8), (x, grabber["y"] + 300))
    expect(dialog).to_be_hidden()


@pytest.mark.restic
def test_backup_set_up_history_and_restore_on_a_phone(
    phone_page, expect, restic_binary: Path, tmp_path: Path
) -> None:
    page = phone_page
    page.goto(f"{_origin(page)}/admin?section=backup")
    expect(page.get_by_role("heading", name="Backups are off")).to_be_visible()

    page.get_by_role("button", name="Set up backups").tap()
    page.get_by_label("Backup storage folder").fill(str(tmp_path / "backups"))
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Repeat password").fill(PASSWORD)
    page.get_by_role("checkbox").check()
    assert_mobile_page_fits(page)
    page.get_by_role("button", name="Create and back up now").tap()

    history = page.get_by_role("region", name="Backup history")
    expect(history.get_by_role("row").nth(1)).to_contain_text(
        "Backed up", timeout=RESTIC_TIMEOUT_MS
    )
    assert_mobile_page_fits(page)

    # Backup's two pages sit under the chips once it is on.
    chips = page.get_by_role("navigation", name="Admin sections")
    expect(chips.get_by_role("link", name="Status and history")).to_have_attribute(
        "aria-current", "page"
    )

    history.get_by_role("button", name="Restore…").first.tap()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    page.wait_for_function("() => document.getAnimations().length === 0")
    box = dialog.bounding_box()
    assert box["y"] + box["height"] == pytest.approx(page.viewport_size["height"], abs=1)
    grabber = page.locator(".bk-dialog .sheet-grabber").bounding_box()
    x = grabber["x"] + grabber["width"] / 2
    swipe(page, (x, grabber["y"] + 8), (x, grabber["y"] + 300))
    expect(dialog).to_be_hidden()

    # A click, not a tap: right after a swipe from the CDP helper, emulated
    # Chrome sometimes drops the next Playwright tap's click (touchend fires,
    # click never does). Taps on the chips are covered above.
    chips.get_by_role("link", name="Setup").click()
    page.get_by_role("heading", name="Backup settings").wait_for(state="visible")
    assert_mobile_page_fits(page)

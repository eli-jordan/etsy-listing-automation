"""The calibrator (Mockup Templates) on a phone, driven with a finger: the
header's template switcher and its sheet, dragging a box corner, the box
actions a right-click gives on the desktop, the Marigold mask brush, and the
inference settings sheet."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.support.marigold import PreparationRuntime, marigold_template
from tests.support.mobile import assert_mobile_page_fits, swipe

pytestmark = pytest.mark.browser

MARIGOLD = "marigold-shirt"


@pytest.fixture
def preparation_runtime() -> PreparationRuntime:
    return PreparationRuntime()


@pytest.fixture
def app_options(workspace_root: Path, preparation_runtime: PreparationRuntime) -> dict:
    marigold_template(workspace_root, "single", name=MARIGOLD, renderer="photo-warp")
    return {"preparation_runtime": preparation_runtime}


def _template_config(workspace_root: Path, template: str) -> dict:
    path = workspace_root / "mockup-templates" / template / "template.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _open_calibrator(page):
    origin = page.url.rstrip("/")
    page.goto(f"{origin}/templates")
    page.locator(".tswitch__name").wait_for(state="visible")
    return origin


def _current(page) -> str:
    return page.locator(".tswitch__name").inner_text().strip()


def _pick(page, name: str, *, after_swipe: bool = False) -> None:
    """Choose a template from the header's sheet.

    Under DevTools touch emulation the first tap after a ``swipe`` reaches
    the page as pointerdown/up with no click (seen on the foundation's sheet
    grabber too), so a pick that follows a swipe clicks instead."""

    def press(locator) -> None:
        if after_swipe:
            locator.click()
        else:
            locator.tap()

    press(page.locator(".tswitch__current"))
    sheet = page.get_by_role("dialog", name="Templates")
    sheet.wait_for(state="visible")
    press(sheet.locator(f".template-rail__item[data-template='{name}']"))
    sheet.wait_for(state="detached")
    page.wait_for_function(
        "(n) => document.querySelector('.tswitch__name')?.textContent === n", arg=name
    )


def _centre(box: dict) -> tuple[float, float]:
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _config_saved(page):
    return page.expect_response(
        lambda r: r.url.endswith("/config") and r.request.method == "PUT" and r.status == 200
    )


def test_the_header_switches_templates_by_arrow_swipe_and_sheet(phone_page) -> None:
    page = phone_page
    _open_calibrator(page)
    # The rail does not sit beside the canvas on a phone; the header replaces it.
    assert page.locator(".app__workbench .template-rail").count() == 0
    assert _current(page) == "colour-chart-01"
    assert page.get_by_role("button", name="Previous template").is_disabled()
    assert_mobile_page_fits(page)

    page.get_by_role("button", name="Next template").tap()
    page.wait_for_function(
        "() => document.querySelector('.tswitch__name')?.textContent !== 'colour-chart-01'"
    )
    stepped = _current(page)

    # A swipe right on the header goes back; left goes forward again.
    header = _centre(page.locator(".tswitch__current").bounding_box())
    swipe(page, (header[0] - 80, header[1]), (header[0] + 80, header[1]))
    page.wait_for_function(
        "() => document.querySelector('.tswitch__name')?.textContent === 'colour-chart-01'"
    )
    swipe(page, (header[0] + 80, header[1]), (header[0] - 80, header[1]))
    page.wait_for_function(
        "(n) => document.querySelector('.tswitch__name')?.textContent === n", arg=stepped
    )

    _pick(page, "flat-lay-01", after_swipe=True)
    page.get_by_label("Colour").wait_for(state="visible")
    assert_mobile_page_fits(page)


def test_the_sheet_renames_the_open_template_and_swipes_away(
    phone_page, workspace_root: Path
) -> None:
    page = phone_page
    _open_calibrator(page)
    page.locator(".tswitch__current").tap()
    sheet = page.get_by_role("dialog", name="Templates")
    sheet.wait_for(state="visible")

    sheet.get_by_role("button", name="Rename", exact=True).tap()
    sheet.get_by_label("Template name").fill("chart-renamed")
    sheet.get_by_role("button", name="Save name", exact=True).tap()
    page.wait_for_function(
        "() => document.querySelector('.tswitch__name')?.textContent === 'chart-renamed'"
    )
    assert (workspace_root / "mockup-templates" / "chart-renamed" / "template.yaml").exists()
    assert not (workspace_root / "mockup-templates" / "colour-chart-01").exists()

    page.wait_for_function("() => document.getAnimations().length === 0")
    grabber = _centre(page.locator(".tsheet__dialog .sheet-grabber").bounding_box())
    swipe(page, grabber, (grabber[0], grabber[1] + 300))
    sheet.wait_for(state="detached")


def test_a_finger_drags_a_corner_without_scrolling_and_the_save_writes_it(
    phone_page, workspace_root: Path
) -> None:
    page = phone_page
    _open_calibrator(page)
    _pick(page, "flat-lay-01")
    before = _template_config(workspace_root, "flat-lay-01")["bounding_box"]

    grip = page.locator(".quad-editor__grip[data-corner='0']")
    grip.scroll_into_view_if_needed()
    box = grip.bounding_box()
    # The grip is finger-sized although the dot drawn under it is small.
    assert box["width"] >= 40
    assert box["height"] >= 40
    x, y = _centre(box)
    scrolled = page.evaluate("scrollY")
    with _config_saved(page):
        # Start off the dot's centre, inside the grip: a finger is imprecise.
        swipe(page, (x + 12, y + 12), (x + 60, y + 70))
    assert page.evaluate("scrollY") == scrolled

    after = _template_config(workspace_root, "flat-lay-01")["bounding_box"]
    assert after[0] != before[0]
    assert after[1:] == before[1:]

    # A finger on the photo outside the box still scrolls the page.
    image = page.locator(".quad-editor__image").bounding_box()
    start = (image["x"] + 6, image["y"] + image["height"] - 8)
    swipe(page, start, (start[0], start[1] - 150))
    page.wait_for_function("(y) => scrollY > y", arg=scrolled)


def test_a_multiple_template_adds_and_deletes_boxes_with_buttons(
    phone_page, workspace_root: Path
) -> None:
    page = phone_page
    _open_calibrator(page)
    _pick(page, "colour-chart-01")
    actions = page.get_by_role("toolbar", name="Boxes")
    actions.scroll_into_view_if_needed()
    with _config_saved(page):
        actions.get_by_role("button", name="+ Add box").tap()
    page.wait_for_function("() => document.querySelectorAll('.quad-editor__polygon').length === 3")
    assert len(_template_config(workspace_root, "colour-chart-01")["placements"]) == 3

    with _config_saved(page):
        actions.get_by_role("button", name="Delete").tap()
    page.wait_for_function("() => document.querySelectorAll('.quad-editor__polygon').length === 2")
    assert len(_template_config(workspace_root, "colour-chart-01")["placements"]) == 2
    assert_mobile_page_fits(page)


def _prepare_marigold(page) -> None:
    _pick(page, MARIGOLD)
    page.get_by_label("Renderer", exact=True).select_option("marigold")
    page.get_by_role("button", name="Prepare template", exact=True).tap()
    page.wait_for_function(
        "() => document.querySelector('.mg-preparation .mg-status')?.textContent === 'Ready'"
    )


def test_the_mask_brush_paints_with_a_finger(phone_page) -> None:
    page = phone_page
    _open_calibrator(page)
    _prepare_marigold(page)

    page.get_by_role("button", name="Edit mask", exact=True).tap()
    dock = page.get_by_role("toolbar", name="Mask brushes")
    dock.wait_for(state="visible")
    for name in ["Mask", "Unmask", "Undo brush stroke", "Reset mask", "Done"]:
        assert dock.get_by_role("button", name=name, exact=True).bounding_box()["height"] >= 40
    area = page.get_by_label("Mask drawing area")
    area.scroll_into_view_if_needed()
    bounds = area.bounding_box()
    scrolled = page.evaluate("scrollY")
    start = (bounds["x"] + bounds["width"] * 0.3, bounds["y"] + bounds["height"] * 0.3)
    end = (bounds["x"] + bounds["width"] * 0.6, bounds["y"] + bounds["height"] * 0.7)
    swipe(page, start, end)
    assert page.evaluate("scrollY") == scrolled
    assert dock.get_by_role("button", name="Undo brush stroke", exact=True).is_enabled()

    with _config_saved(page) as saved:
        dock.get_by_role("button", name="Done", exact=True).tap()
    operation = saved.value.request.post_data_json["mask_edits"][0]["operations"][0]
    assert operation["type"] == "stroke"
    assert len(operation["points"]) > 2
    assert_mobile_page_fits(page)


def test_the_inference_settings_are_a_sheet_that_swipes_away(phone_page) -> None:
    page = phone_page
    _open_calibrator(page)
    _pick(page, MARIGOLD)
    page.get_by_label("Renderer", exact=True).select_option("marigold")
    page.get_by_role("button", name="Advanced settings").tap()
    dialog = page.get_by_role("dialog", name="Advanced Marigold Settings")
    dialog.wait_for(state="visible")
    page.wait_for_function("() => document.getAnimations().length === 0")
    sheet = page.locator(".mi-sheet").bounding_box()
    viewport = page.viewport_size
    assert sheet["width"] == pytest.approx(viewport["width"], abs=1)
    assert sheet["y"] + sheet["height"] == pytest.approx(viewport["height"], abs=1)

    grabber = _centre(page.locator(".mi-sheet .sheet-grabber").bounding_box())
    swipe(page, grabber, (grabber[0], grabber[1] + 300))
    dialog.wait_for(state="detached")

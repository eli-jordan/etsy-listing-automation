"""The Organic design system, asserted through computed style.

A stylesheet can *contain* a token and still not reach the pixel -- a shadowed
selector, a stale build, an unimported file. Everything here therefore reads
`getComputedStyle` on the running app rather than the CSS source, which is the
same reason the rest of the browser layer asserts on decoded PNGs instead of
component state.

Colour assertions carry the hex they came from, because a bare `rgb(245, 234,
216)` in a diff tells the next reader nothing about which token moved.

Screenshots are written to `_screenshots/` (gitignored) for human review
against the 2a wireframe; no pixel comparison happens here, since a browser
screenshot is far more platform-fragile than the render goldens are.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

PREVIEW_IMAGE = "img.quad-editor__image"

# _ds/organic-…/styles.css. The ground, the ink and the two accents.
ORGANIC_BG = "#f5ead8"
ORGANIC_TEXT = "#201e1d"
ORGANIC_ACCENT = "#c67139"
ORGANIC_ACCENT_2 = "#7a8a5e"
ORGANIC_SURFACE = "#ebddc5"


def _rgb(hex_colour: str) -> str:
    """`#f5ead8` -> `rgb(245, 234, 216)`, the shape getComputedStyle returns."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgb({r}, {g}, {b})"


@pytest.fixture
def screenshot_dir() -> Path:
    directory = Path(
        os.environ.get("CALIBRATOR_SCREENSHOT_DIR", Path(__file__).parent / "_screenshots")
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _token(page, name: str) -> str:  # noqa: ANN001
    """Read a custom property off :root, trimmed."""
    return page.evaluate(
        f"() => getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()"
    )


def _computed(page, selector: str, prop: str) -> str:  # noqa: ANN001
    return page.evaluate(
        f"() => {{ const el = document.querySelector('{selector}');"
        f"  return el && getComputedStyle(el).getPropertyValue('{prop}'); }}"
    )


class TestOrganicTokens:
    """The token layer is vendored from the design system, so these values are
    the contract between it and us -- if one drifts, the page has silently
    stopped being Organic."""

    def test_root_defines_the_organic_palette(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        assert _token(page, "--color-bg") == ORGANIC_BG
        assert _token(page, "--color-text") == ORGANIC_TEXT
        assert _token(page, "--color-accent") == ORGANIC_ACCENT
        assert _token(page, "--color-accent-2") == ORGANIC_ACCENT_2
        assert _token(page, "--color-surface") == ORGANIC_SURFACE

    def test_root_defines_the_scales(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        # Density 1.10x from the vendored Organic; radii are flattened to a
        # single 4px by the app's :root override (index.css:347) for boxes,
        # inputs and buttons.
        assert _token(page, "--space-3") == "13.2px"
        assert _token(page, "--radius-md") == "4px"
        assert _token(page, "--radius-lg") == "4px"
        assert _token(page, "--shadow-md") != ""

    def test_tonal_ramps_are_present(self, page) -> None:  # noqa: ANN001
        """All three roles carry a 100-900 ramp; tinted fills and pressed
        states come from these rather than ad-hoc color-mix()."""
        page.wait_for_selector(PREVIEW_IMAGE)
        for role in ("neutral", "accent", "accent-2"):
            for step in (100, 500, 900):
                assert _token(page, f"--color-{role}-{step}") != "", (
                    f"--color-{role}-{step} missing"
                )


class TestOrganicGround:
    def test_body_uses_the_warm_ground_not_the_old_grey(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        assert _computed(page, "body", "background-color") == _rgb(ORGANIC_BG)
        assert _computed(page, "body", "color") == _rgb(ORGANIC_TEXT)

    def test_body_text_is_set_in_the_body_face(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        assert "Figtree" in _computed(page, "body", "font-family")

    def test_headings_use_the_display_face(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        assert "Caprasimo" in _computed(page, "h1", "font-family")


class TestOrganicComponents:
    def test_buttons_are_pills(self, page) -> None:  # noqa: ANN001
        """Buttons now use the flat 4px (via --radius-sm override); only tags,
        chips, switches and circles retain the 999px pill radius."""
        page.wait_for_selector(PREVIEW_IMAGE)
        radius = _computed(page, "button", "border-radius")
        assert radius == "4px", f"expected flat 4px, got {radius}"

    def test_there_is_no_manual_save_action(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        assert page.get_by_role("button", name="Save template.yaml").count() == 0

    def test_unclassed_actions_still_read_as_buttons(self, page) -> None:  # noqa: ANN001
        """`.btn` is deliberately transparent -- the design system expects a
        variant class on every button. The calibrator has plain `<button>`s
        that never got one, and a transparent button is just text: no edge, no
        affordance. The app layer has to give them a default."""
        page.wait_for_selector(PREVIEW_IMAGE)
        # "Duplicate" carries no variant class, which is exactly the case this
        # guards -- the primary actions opt in to `.btn-primary` and would
        # pass whether or not the fallback exists. It lives in the box's
        # right-click menu, now that a chart has no side panel.
        page.locator(".quad-editor__polygon").first.click(button="right")
        plain = page.get_by_role("menuitem", name="Duplicate")
        plain.wait_for()
        assert plain.evaluate("el => getComputedStyle(el).backgroundColor") != "rgba(0, 0, 0, 0)"

    def test_the_preview_sits_on_the_surface_tone(self, page) -> None:  # noqa: ANN001
        """The photo frame was a cold #e5e5e5; on a warm ground that reads as
        a hole in the page."""
        page.wait_for_selector(PREVIEW_IMAGE)
        assert _computed(page, ".app__preview", "background-color") == _rgb(ORGANIC_SURFACE)

    def test_the_selected_tab_is_the_one_that_looks_selected(self, page) -> None:  # noqa: ANN001
        """`.seg-opt` and `.seg-opt--on` have the same specificity, so source
        order decides -- and with the base rule last, the *active* tab rendered
        as the grey one. Backwards, and invisible in a unit test."""
        # The Calibrate/Preview tabs belong to the colour-matrix editor; the
        # chart kind (which loads first) has no second view to switch to.
        row = page.locator(".template-rail__item[data-template='flat-lay-01']")
        row.wait_for()
        row.click()
        active = page.get_by_role("tab", name="Calibrate")
        active.wait_for()
        assert active.evaluate("el => getComputedStyle(el).backgroundColor") == _rgb(ORGANIC_ACCENT)

    def test_the_quad_overlay_is_drawn_in_the_accent(self, page) -> None:  # noqa: ANN001
        """The old overlay was hardcoded #3f7dff -- a blue that belongs to no
        token and fights the warm ground."""
        page.wait_for_selector(PREVIEW_IMAGE)
        stroke = _computed(page, ".quad-editor__polygon", "stroke")
        assert stroke == _rgb(ORGANIC_ACCENT), f"overlay still {stroke}"


def test_no_console_errors_with_the_new_stylesheet(page) -> None:  # noqa: ANN001
    """The stylesheet pulls Caprasimo and Figtree from Google Fonts at runtime,
    so this doubles as the guard on that decision: a font request that starts
    erroring shows up here rather than as a silently plain-looking page."""
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.reload()
    page.wait_for_selector(PREVIEW_IMAGE)
    assert errors == []


def test_capture_full_page_screenshot(page, screenshot_dir: Path) -> None:  # noqa: ANN001
    """Not an assertion about looks -- it produces the artifact a human (or
    Claude) reviews against the wireframe. Fails only if the page won't paint."""
    page.wait_for_selector(PREVIEW_IMAGE)
    page.wait_for_timeout(400)  # let the first preview render land
    target = screenshot_dir / "phase1-colour-matrix.png"
    page.screenshot(path=str(target), full_page=True)
    assert target.stat().st_size > 0


def test_capture_preview_all_screenshot(page, screenshot_dir: Path) -> None:  # noqa: ANN001
    """The Preview tab with every colour rendered -- the state you approve
    from, and the only place the grid exists.

    Opening the tab is what asks for it; there is no separate button for a
    first look, only a Re-render for afterwards."""
    row = page.locator(".template-rail__item[data-template='flat-lay-01']")
    row.wait_for()
    row.click()
    page.wait_for_selector(PREVIEW_IMAGE)
    page.get_by_role("tab", name="Preview").click()
    page.wait_for_function(
        "() => document.querySelectorAll('.preview-grid__tile img').length === 4"
    )
    target = screenshot_dir / "phase6-preview-all.png"
    page.screenshot(path=str(target), full_page=True)
    assert target.stat().st_size > 0


def test_capture_lightbox_screenshot(page, screenshot_dir: Path) -> None:  # noqa: ANN001
    """A rendered preview opened large -- where a calibration is actually
    judged, and the reason the Preview tab renders at full size at all."""
    row = page.locator(".template-rail__item[data-template='flat-lay-01']")
    row.wait_for()
    row.click()
    page.wait_for_selector(PREVIEW_IMAGE)
    page.get_by_role("tab", name="Preview").click()
    page.wait_for_function(
        "() => document.querySelectorAll('.preview-grid__tile img').length === 4"
    )
    page.locator(".preview-grid__open").first.click()
    page.wait_for_function("() => document.querySelector('.lightbox__image')?.naturalWidth > 0")
    target = screenshot_dir / "phase7-lightbox.png"
    page.screenshot(path=str(target))
    assert target.stat().st_size > 0


def test_capture_multiple_editor_screenshot(page, screenshot_dir: Path) -> None:  # noqa: ANN001
    """The chart editor with a box selected -- the colour captions, the extent
    readout and the Add box affordance are the parts that only exist here."""
    row = page.locator(".template-rail__item[data-template='colour-chart-01']")
    row.wait_for()
    row.click()
    page.wait_for_selector(".quad-editor__label")
    page.wait_for_timeout(600)
    target = screenshot_dir / "phase5-multiple-editor.png"
    page.screenshot(path=str(target), full_page=True)
    assert target.stat().st_size > 0


def test_capture_workbench_screenshot(  # noqa: ANN001
    page, screenshot_dir: Path, workspace_root: Path
) -> None:
    """The three-column workbench with an uncalibrated template present -- the
    state wireframe 2a is drawn in. The fixture workspace is otherwise fully
    calibrated, so the rail's banner and its whole top group would be missing
    and the screenshot would not show what it is meant to show."""
    (workspace_root / "mockup-templates" / "boxy-tee").mkdir(exist_ok=True)
    page.reload()
    # Open a calibrated template, or the canvas and inspector columns are
    # empty and the shot shows only one of the three.
    row = page.locator(".template-rail__item[data-template='flat-lay-01']")
    row.wait_for()
    row.click()
    page.wait_for_selector(PREVIEW_IMAGE)
    page.wait_for_timeout(600)
    target = screenshot_dir / "phase2-workbench.png"
    page.screenshot(path=str(target), full_page=True)
    assert target.stat().st_size > 0

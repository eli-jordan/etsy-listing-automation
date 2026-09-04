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
        # Density 1.10x and radius 16px are baked into these by the generator;
        # components must read them rather than raw px.
        assert _token(page, "--space-3") == "13.2px"
        assert _token(page, "--radius-md") == "16px"
        assert _token(page, "--radius-lg") == "28px"
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
        """`.btn, .tag, .seg, .input { border-radius: 999px }` -- the rounded
        frame is the system's most recognisable move."""
        page.wait_for_selector(PREVIEW_IMAGE)
        radius = _computed(page, "button", "border-radius")
        assert radius == "999px", f"expected a pill, got {radius}"

    def test_the_primary_action_is_a_solid_accent_fill(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(PREVIEW_IMAGE)
        save = page.get_by_role("button", name="Save template.yaml")
        assert save.evaluate("el => getComputedStyle(el).backgroundColor") == _rgb(ORGANIC_ACCENT)

    def test_unclassed_actions_still_read_as_buttons(self, page) -> None:  # noqa: ANN001
        """`.btn` is deliberately transparent -- the design system expects a
        variant class on every button. The calibrator has plain `<button>`s
        that never got one, and a transparent button is just text: no edge, no
        affordance. The app layer has to give them a default."""
        page.wait_for_selector(PREVIEW_IMAGE)
        add = page.get_by_role("button", name="Add placement")
        assert add.evaluate("el => getComputedStyle(el).backgroundColor") != "rgba(0, 0, 0, 0)"

    def test_the_preview_sits_on_the_surface_tone(self, page) -> None:  # noqa: ANN001
        """The photo frame was a cold #e5e5e5; on a warm ground that reads as
        a hole in the page."""
        page.wait_for_selector(PREVIEW_IMAGE)
        assert _computed(page, ".app__preview", "background-color") == _rgb(ORGANIC_SURFACE)

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

"""Browser tests for the calibrator, one flow per template kind.

These cover the one thing no other layer can: that the React app, the FastAPI
endpoints and the real render pipeline actually work *together* in a
browser -- a drag reaching the server, a PNG coming back, and autosave writing
the template.yaml that `apply` will later read.

They run against the built SPA served by FastAPI (see conftest), and skip
cleanly when playwright or its chromium build is missing, so they are part of
the ordinary suite rather than something you have to remember to run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.browser

COLOUR_MATRIX_TEMPLATE = "flat-lay-01"
MULTIPLE_TEMPLATE = "colour-chart-01"
HANDLE = "circle.quad-editor__handle"
PREVIEW_IMAGE = "img.quad-editor__image"

# The synthetic template sets' pixel sizes (scripts/generate_test_assets.py).
COLOUR_MATRIX_SIZE = (480, 576)
CHART_SIZE = (960, 576)


def _extent(box: list[dict]) -> tuple[float, float]:
    xs = [p["x"] for p in box]
    ys = [p["y"] for p in box]
    return max(xs) - min(xs), max(ys) - min(ys)


def _aspect(box: list[dict]) -> float:
    width, height = _extent(box)
    return width / height


def _template_config(workspace_root: Path, template: str) -> dict:  # noqa: ANN401
    return yaml.safe_load(
        (workspace_root / "mockup-templates" / template / "template.yaml").read_text(
            encoding="utf-8"
        )
    )


def _rail_row(page, name: str):  # noqa: ANN001, ANN201
    """Wireframe 2a replaced the template dropdown with the rail, so picking a
    template is a click on its row. `data-template` is the hook rather than a
    presentational class: the row's look is still being worked on, and a test
    that breaks when a border-radius changes is worse than no test."""
    return page.locator(f".template-rail__item[data-template='{name}']")


def _select_template(page, name: str) -> None:  # noqa: ANN001
    row = _rail_row(page, name)
    row.wait_for()
    row.click()


def _selected_template(page) -> str | None:  # noqa: ANN001
    page.wait_for_selector(".template-rail__item--active")
    return page.locator(".template-rail__item--active").first.get_attribute("data-template")


class TrafficLog:
    """Records matching *responses* from the moment it is created.

    Two things this gets right that `page.expect_response(...)` does not.
    It listens from construction rather than only inside a `with` block, so a
    response that arrives early is still seen -- under the whole suite these
    fired both early and late, failing a different test each run. And it waits
    on the response, not the request: a test that reads template.yaml straight
    after a PUT needs the server to have *finished*, not merely to have been
    asked. (Waiting on the request instead made that read race the write, and
    yaml.safe_load returned None on the half-written file.)

    Responses carry their request, so a payload assertion still works.
    """

    def __init__(self, page, needle: str) -> None:  # noqa: ANN001
        self.page = page
        self.entries: list[object] = []
        page.on(
            "response",
            lambda response: self.entries.append(response) if needle in response.url else None,
        )

    def wait_for(self, predicate, timeout_ms: int = 60_000):  # noqa: ANN001, ANN201
        for _ in range(timeout_ms // 100):
            for response in list(self.entries):
                if predicate(response):
                    return response
            self.page.wait_for_timeout(100)
        raise AssertionError(f"no matching response in {timeout_ms}ms ({len(self.entries)} seen)")


def _sent(response) -> dict:  # noqa: ANN001, ANN401
    """The JSON body of the request that produced this response."""
    return json.loads(response.request.post_data or "{}")


def _method(response) -> str:  # noqa: ANN001
    return str(response.request.method)


COLOUR_SELECT = ".app__bar-field select"


def _wait_for_colours(page, count: int) -> None:  # noqa: ANN001
    """Wait for the colour dropdown to be *fully* populated.

    `wait_for_selector` returns as soon as the select exists, but its colours
    arrive with the template list refresh -- so reading the options straight
    after it can catch the list mid-build. That is a genuinely intermittent
    failure, not a slow machine, so the wait has to be on the count.
    """
    page.wait_for_function(
        f"() => document.querySelectorAll('{COLOUR_SELECT} option').length === {count}"
    )


def _colours(page) -> list[str]:  # noqa: ANN001
    return page.locator(f"{COLOUR_SELECT} option").all_inner_texts()


def _image_natural_size(page) -> list[int]:  # noqa: ANN001
    page.wait_for_function(
        "() => document.querySelector('img.quad-editor__image')?.naturalWidth > 0"
    )
    return page.evaluate(
        "() => { const i = document.querySelector('img.quad-editor__image');"
        "  return [i.naturalWidth, i.naturalHeight]; }"
    )


def _overlay_space(page) -> list[int]:  # noqa: ANN001
    """The coordinate space the box overlay is working in.

    This, not the image's own size, is what a dragged box is saved in. The
    editor renders a *downscale* now, so the two are different numbers for any
    photo bigger than the cap -- and reading the image instead is precisely the
    bug that would silently save every box several times too small.
    """
    page.wait_for_selector(".quad-editor__overlay")
    box = page.locator(".quad-editor__overlay").first.get_attribute("viewBox") or ""
    return [int(float(n)) for n in box.split()[2:]]


def test_calibrator_loads_the_workspace_templates(page) -> None:  # noqa: ANN001
    page.wait_for_selector(PREVIEW_IMAGE)
    assert page.locator("h1").inner_text() == "Mockup Templates"
    listed = page.locator(".template-rail__item").evaluate_all(
        "rows => rows.map(r => r.dataset.template)"
    )
    assert COLOUR_MATRIX_TEMPLATE in listed
    assert MULTIPLE_TEMPLATE in listed


def test_no_console_errors_on_load(page) -> None:  # noqa: ANN001
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.reload()
    page.wait_for_selector(PREVIEW_IMAGE)
    assert errors == []


# --- colour-matrix kind ------------------------------------------------


class TestTemplateRail:
    """The rail is the template picker now, so the things worth proving in a
    real browser are that it lists the workspace, that its thumbnails are
    images the browser can actually decode (a broken <img> still has a DOM
    node), and that picking a row loads that template."""

    def test_rail_lists_the_workspace_and_groups_by_state(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        (workspace_root / "mockup-templates" / "needs-a-kind").mkdir()
        page.reload()
        page.wait_for_selector(".template-rail__item")

        # inner_text() is the *rendered* text, and the heading is uppercased in
        # CSS -- the casing is presentation, so compare without it.
        headings = [h.lower() for h in page.locator(".template-rail__heading").all_inner_texts()]
        assert "needs calibration · 1" in headings
        assert "calibrated · 2" in headings

    def test_the_banner_offers_the_next_uncalibrated_template(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        (workspace_root / "mockup-templates" / "needs-a-kind").mkdir()
        page.reload()
        page.wait_for_selector(".template-rail__banner")
        assert "1 template needs calibration" in page.locator(".template-rail__banner").inner_text()

        page.get_by_role("button", name="Calibrate next →").click()
        assert _selected_template(page) == "needs-a-kind"

    def test_rail_thumbnails_decode_as_real_images(self, page) -> None:  # noqa: ANN001
        """Served by /thumbnail off the template's own photo -- if the endpoint
        404s or returns something that isn't a PNG, naturalWidth stays 0."""
        # `img.` explicitly: a template with no photo renders a <span> tile
        # wearing the same class, and a span has no naturalWidth.
        page.wait_for_selector("img.template-rail__thumb")
        page.wait_for_function(
            "() => [...document.querySelectorAll('img.template-rail__thumb')]"
            ".every(i => i.complete && i.naturalWidth > 0)"
        )
        widths = page.locator("img.template-rail__thumb").evaluate_all(
            "imgs => imgs.map(i => i.naturalWidth)"
        )
        assert widths and all(0 < w <= 160 for w in widths)

    def test_searching_narrows_the_rail(self, page) -> None:  # noqa: ANN001
        page.wait_for_selector(".template-rail__item")
        page.get_by_label("Search templates").fill("chart")
        listed = page.locator(".template-rail__item").evaluate_all(
            "rows => rows.map(r => r.dataset.template)"
        )
        assert listed == [MULTIPLE_TEMPLATE]

    def test_picking_a_row_loads_that_template(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(COLOUR_SELECT)
        assert _selected_template(page) == COLOUR_MATRIX_TEMPLATE
        assert list(_image_natural_size(page)) == list(COLOUR_MATRIX_SIZE)


class TestColourMatrixKind:
    def test_the_colour_dropdown_lists_every_colour_in_the_set(self, page) -> None:  # noqa: ANN001
        """A row of pills used to sit between the tabs and the photo, pushing
        the thing being calibrated down the page and wrapping onto two lines
        for a real garment's colour range. It is a choice of one from a list."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        _wait_for_colours(page, 4)
        assert _colours(page) == ["black", "blue-jean", "ivory", "moss"]

    def test_the_editor_previews_through_the_real_renderer_at_editor_scale(  # noqa: ANN001
        self, page
    ) -> None:
        """The preview must be a real server render, not a client-side
        stand-in -- the proof is that the browser *decoded* an image the
        server produced, sized by the pipeline rather than by the page.

        The canvas asks for `scale=editor`, which is the cheap WebP frame a
        drag can afford. This set is 480x576, inside the cap, so it happens to
        come back at its own size; what is being pinned is the request and the
        decode, not the arithmetic (that is the API layer's job).
        """
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        with page.expect_response(
            lambda r: "/preview" in r.url and r.status == 200
        ) as response_info:
            page.reload()
            _select_template(page, COLOUR_MATRIX_TEMPLATE)
        assert "scale=editor" in response_info.value.url
        assert response_info.value.headers["content-type"] == "image/webp"
        assert list(_image_natural_size(page)) == list(COLOUR_MATRIX_SIZE)

    def test_the_overlay_works_in_the_template_true_pixel_space(self, page) -> None:  # noqa: ANN001
        """Told by the API, not measured off the image. The two agree for this
        set, and the chart below is where they part company."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        assert _overlay_space(page) == list(COLOUR_MATRIX_SIZE)

    def test_selecting_a_colour_rerenders_that_colour(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        _wait_for_colours(page, 4)
        log = TrafficLog(page, "/preview")
        page.locator(COLOUR_SELECT).select_option("moss")
        log.wait_for(lambda r: _sent(r).get("colour") == "moss" and r.status == 200)
        assert page.locator(COLOUR_SELECT).input_value() == "moss"

    def test_the_preview_tab_renders_the_set_at_full_size(self, page) -> None:  # noqa: ANN001
        """The other half of the split: the canvas renders small so dragging is
        instant, and this tab renders the real thing.

        Opening it is the ask -- there is no separate button to press for a
        first look. Every tile is a real server render, so this waits for the
        count rather than for the tiles, which are placeholders from the start.
        """
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        # Mounted behind the canvas, and therefore genuinely hidden: the panel
        # sets `display: flex`, which beats the user agent's `[hidden]` rule,
        # so without an explicit hidden case the tab switches nothing.
        assert not page.locator(".preview-grid").is_visible()

        log = TrafficLog(page, "/preview")
        page.get_by_role("tab", name="Preview").click()
        full = log.wait_for(lambda r: "scale=full" in r.url and r.status == 200)
        assert full.headers["content-type"] == "image/png"

        assert page.locator(".preview-grid__tile").count() == 4
        page.wait_for_function(
            "() => document.querySelectorAll('.preview-grid__tile img').length === 4"
        )
        page.wait_for_selector("text=4 / 4")

    def test_moving_a_box_reddens_re_render_instead_of_re_running(self, page) -> None:  # noqa: ANN001
        """A view you approve from must never quietly be a picture of an older
        box than the one on screen. It does not re-run either: a full-size set
        is minutes of work, and a nudge is not a request for it."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        page.get_by_role("tab", name="Preview").click()
        page.wait_for_selector("text=4 / 4")

        re_render = page.get_by_role("button", name="Re-render")
        assert "btn-danger" not in (re_render.get_attribute("class") or "")

        page.get_by_role("tab", name="Calibrate").click()
        page.wait_for_selector(HANDLE)
        handle = page.locator(HANDLE).first
        spot = handle.bounding_box()
        assert spot is not None
        page.mouse.move(spot["x"] + spot["width"] / 2, spot["y"] + spot["height"] / 2)
        page.mouse.down()
        page.mouse.move(spot["x"] + 60, spot["y"] + 40, steps=6)
        page.mouse.up()

        log = TrafficLog(page, "scale=full")
        page.get_by_role("tab", name="Preview").click()
        page.wait_for_function(
            "() => document.querySelector('.preview-grid__actions .btn-danger') !== null"
        )
        # The tiles that are up are the ones already rendered, untouched.
        assert page.locator(".preview-grid__tile img").count() == 4
        assert log.entries == []

    def test_a_tile_opens_at_full_size_for_checking(self, page) -> None:  # noqa: ANN001
        """A 140px tile cannot answer the questions calibration is about, so
        the point of rendering full-size is being able to look at it that way."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        page.get_by_role("tab", name="Preview").click()
        page.wait_for_selector("text=4 / 4")

        page.locator(".preview-grid__open").first.click()
        dialog = page.locator(".lightbox")
        dialog.wait_for()
        page.wait_for_function("() => document.querySelector('.lightbox__image')?.naturalWidth > 0")
        assert (
            page.evaluate("() => document.querySelector('.lightbox__image').naturalWidth")
            == COLOUR_MATRIX_SIZE[0]
        )

        page.keyboard.press("Escape")
        assert dialog.count() == 0

    def test_approving_from_the_preview_tab_writes_the_config(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """ "Approve & mark calibrated" is a save. There is no separate stored
        flag -- status is derived -- so the observable effect is template.yaml."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        page.get_by_role("tab", name="Preview").click()

        save_log = TrafficLog(page, "/config")
        page.get_by_role("button", name="Approve & mark calibrated").click()
        save_log.wait_for(lambda r: _method(r) == "PUT" and r.status == 200)
        assert _template_config(workspace_root, COLOUR_MATRIX_TEMPLATE)["kind"] == "colour-matrix"

    def test_hiding_the_placement_outline_leaves_a_clean_render(self, page) -> None:  # noqa: ANN001
        """A colour set has one box and it is always selected, so "clean" here
        means no chrome at all -- unlike a chart, where the toggle only hides
        the boxes you are not working on."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(HANDLE)
        page.get_by_label("show placement outline").uncheck()
        page.wait_for_function("() => document.querySelectorAll('.quad-editor__box').length === 0")
        assert page.locator(HANDLE).count() == 0

    def test_dragging_a_handle_moves_it_and_rerenders(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(HANDLE)
        handle = page.locator(HANDLE).first
        before = handle.bounding_box()
        assert before is not None

        with page.expect_response(lambda r: "/preview" in r.url and r.status == 200):
            page.mouse.move(before["x"] + before["width"] / 2, before["y"] + before["height"] / 2)
            page.mouse.down()
            page.mouse.move(before["x"] + 120, before["y"] + 90, steps=10)
            page.mouse.up()

        after = page.locator(HANDLE).first.bounding_box()
        assert after is not None
        assert (after["x"], after["y"]) != (before["x"], before["y"])

    def test_toggling_the_wrinkle_pass_rerenders_with_the_new_setting(  # noqa: ANN001
        self, page
    ) -> None:
        """The control is named for what it does to the photograph now, but it
        still writes `displace` -- this is the test that the rename stayed a
        rename and did not quietly repoint the toggle."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        log = TrafficLog(page, "/preview")
        page.get_by_label("Follow fabric wrinkles").check()
        log.wait_for(lambda r: _sent(r).get("displace", {}).get("enabled") is True)

    def test_the_shading_presets_write_a_blend_mode(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        log = TrafficLog(page, "/preview")
        page.get_by_role("button", name="Rich").click()
        log.wait_for(lambda r: _sent(r).get("shade", {}).get("blend") == "multiply")

    def test_choosing_a_test_design_rerenders_against_it(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        log = TrafficLog(page, "/preview")
        page.get_by_label("Test design").select_option("bundled-on-dark")
        log.wait_for(lambda r: _sent(r).get("design") == "bundled-on-dark")

    def test_saving_writes_the_dragged_box_to_template_yaml(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """The full loop the calibrator exists for: drag, save, and the
        geometry is on disk in the file the render stage reads."""
        original = _template_config(workspace_root, COLOUR_MATRIX_TEMPLATE)["bounding_box"]

        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(HANDLE)
        handle = page.locator(HANDLE).first
        box = handle.bounding_box()
        assert box is not None

        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + 100, box["y"] + 70, steps=10)
        page.mouse.up()

        save_log = TrafficLog(page, "/config")
        save_log.wait_for(lambda r: _method(r) == "PUT" and r.status == 200)
        page.wait_for_selector("text=Saved")

        saved = _template_config(workspace_root, COLOUR_MATRIX_TEMPLATE)
        assert saved["kind"] == "colour-matrix"
        assert saved["bounding_box"] != original
        assert len(saved["bounding_box"]) == 4


# --- multiple kind -------------------------------------------------------


class TestMultipleKind:
    """A chart's boxes are edited entirely on the photo now -- there is no
    bounding-box panel. Everything the panel offered was already on the canvas
    except assigning a colour, and that is a caption on the box itself."""

    def test_every_placement_is_a_box_with_its_colour_written_on_it(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        assert page.locator(".quad-editor__box").count() == 2
        assert page.locator(".quad-editor__label").count() == 2

    def test_the_canvas_draws_a_downscale_over_the_true_coordinate_space(  # noqa: ANN001
        self, page
    ) -> None:
        """The chart is 960px wide, past the 900px editor cap, so this is where
        the image on screen and the space its boxes live in genuinely differ.

        Both halves matter. The image being *smaller* is the performance
        change; the overlay still being in the photo's true space is what keeps
        Save writing coordinates the render stage will read back correctly.
        """
        _select_template(page, MULTIPLE_TEMPLATE)
        with page.expect_response(
            lambda r: "/preview" in r.url and r.status == 200
        ) as response_info:
            page.reload()
            _select_template(page, MULTIPLE_TEMPLATE)
        assert response_info.value.headers["content-type"] == "image/webp"

        assert _overlay_space(page) == list(CHART_SIZE)
        assert _image_natural_size(page)[0] < CHART_SIZE[0]

    def test_shift_dragging_a_corner_resizes_the_box_without_reshaping_it(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """The gesture every kind gains: a print placed right and simply too
        small should not have to be fixed by dragging four corners by four
        different amounts.

        Asserted on template.yaml rather than on screen, because "same shape"
        is a statement about the saved geometry: the box grows and its aspect
        ratio survives.
        """
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(HANDLE)
        before = _template_config(workspace_root, MULTIPLE_TEMPLATE)["placements"][0][
            "bounding_box"
        ]

        handle = page.locator(HANDLE).nth(2)  # bottom-right of the selected box
        spot = handle.bounding_box()
        assert spot is not None
        page.mouse.move(spot["x"] + spot["width"] / 2, spot["y"] + spot["height"] / 2)
        page.mouse.down()
        page.keyboard.down("Shift")
        page.mouse.move(spot["x"] + 60, spot["y"] + 60, steps=10)
        page.mouse.up()
        page.keyboard.up("Shift")

        save_log = TrafficLog(page, "/config")
        save_log.wait_for(lambda r: _method(r) == "PUT" and r.status == 200)

        after = _template_config(workspace_root, MULTIPLE_TEMPLATE)["placements"][0]["bounding_box"]
        assert after != before
        assert _extent(after)[0] > _extent(before)[0]
        assert _aspect(after) == pytest.approx(_aspect(before), rel=0.02)

    def test_clicking_a_dimmed_box_selects_it(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        boxes = page.locator(".quad-editor__box")
        assert boxes.count() == 2
        boxes.nth(1).click()
        # Handles are the answer to "which one am I editing?" -- only the
        # selected box wears them. There is no pill on the photo saying so any
        # more: this view exists to be looked at.
        assert boxes.nth(1).locator(HANDLE).count() == 4
        assert boxes.nth(0).locator(HANDLE).count() == 0

    def test_duplicate_from_the_box_menu_adds_a_third(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        page.locator(".quad-editor__polygon").first.click(button="right")
        page.get_by_role("menuitem", name="Duplicate").click()
        page.wait_for_function("() => document.querySelectorAll('.quad-editor__box').length === 3")

    def test_adding_a_box_from_the_canvas_selects_it(self, page) -> None:  # noqa: ANN001
        """2a puts Add box *on* the photo: a new box lands selected and
        draggable, with no drawing mode to enter first."""
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        page.get_by_role("button", name="+ Add box").click()
        page.wait_for_function("() => document.querySelectorAll('.quad-editor__box').length === 3")
        boxes = page.locator(".quad-editor__box")
        assert boxes.nth(2).locator(HANDLE).count() == 4
        # A box with no colour yet says so, in place, rather than leaving you
        # to work out which row of a list it was.
        assert page.locator(".quad-editor__label--empty").count() == 1

    def test_the_delete_key_removes_the_selected_box(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        page.locator(".quad-editor").click(position={"x": 5, "y": 5})
        page.keyboard.press("Delete")
        page.wait_for_function("() => document.querySelectorAll('.quad-editor__box').length === 1")

    def test_right_clicking_a_box_opens_its_menu(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        page.locator(".quad-editor__polygon").first.click(button="right")
        page.wait_for_selector(".quad-editor__menu")
        items = page.locator(".quad-editor__menu button").all_inner_texts()
        assert items == ["Duplicate", "Bring to front", "Delete ⌫"]

    def test_hiding_the_outlines_leaves_only_the_selected_box(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        assert page.locator(".quad-editor__box").count() == 2
        page.get_by_label("show all outlines").uncheck()
        # The selected box keeps its handles -- the toggle is for judging the
        # render, not for giving up the ability to fix it.
        page.wait_for_function("() => document.querySelectorAll('.quad-editor__box').length === 1")
        assert page.locator(HANDLE).count() == 4
        # The captions are chrome too, so they go with the outlines.
        assert page.locator(".quad-editor__label").count() == 1

    def test_a_colour_typed_on_the_box_reaches_template_yaml(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """The one thing the panel could do that the canvas could not. The
        caption *is* the field now: click it, type, and it is that placement's
        colour."""
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        page.get_by_role("button", name="+ Add box").click()
        page.locator(".quad-editor__label--empty").click()
        page.get_by_label("Colour for box 3").fill("ivory")

        save_log = TrafficLog(page, "/config")
        save_log.wait_for(lambda r: _method(r) == "PUT" and r.status == 200)
        page.wait_for_selector("text=Saved")

        saved = _template_config(workspace_root, MULTIPLE_TEMPLATE)
        assert saved["kind"] == "multiple"
        assert len(saved["placements"]) == 3
        assert saved["placements"][-1]["colour"] == "ivory"


# --- moving a whole box, in every editor ---------------------------------


class TestMovingABox:
    """Getting a box to the right *place* is the commonest move there is, and
    until now the only way to do it was to drag four corners the same distance
    by eye. Both gestures work in every editor, so one is proven on a colour
    set and the other on a chart."""

    def test_dragging_a_box_moves_every_corner_by_the_same_delta(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        original = _template_config(workspace_root, COLOUR_MATRIX_TEMPLATE)["bounding_box"]
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(HANDLE)

        # Press in the middle, well away from any corner handle, and slide.
        area = page.locator(".quad-editor__polygon").first.bounding_box()
        assert area is not None
        centre = (area["x"] + area["width"] / 2, area["y"] + area["height"] / 2)
        page.mouse.move(*centre)
        page.mouse.down()
        page.mouse.move(centre[0] + 60, centre[1] + 40, steps=10)
        page.mouse.up()

        save_log = TrafficLog(page, "/config")
        save_log.wait_for(lambda r: _method(r) == "PUT" and r.status == 200)
        page.wait_for_selector("text=Saved")

        saved = _template_config(workspace_root, COLOUR_MATRIX_TEMPLATE)["bounding_box"]
        moved = {
            (round(after["x"] - before["x"]), round(after["y"] - before["y"]))
            for before, after in zip(original, saved, strict=True)
        }
        # One delta shared by all four corners: the box moved, and kept its
        # shape. Four separate corner drags never gave that.
        assert len(moved) == 1
        assert moved != {(0, 0)}

    def test_arrow_keys_nudge_the_selected_box(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        original = _template_config(workspace_root, MULTIPLE_TEMPLATE)["placements"][0]
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(HANDLE)
        page.locator(".quad-editor").click(position={"x": 5, "y": 5})
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Shift+ArrowDown")

        save_log = TrafficLog(page, "/config")
        save_log.wait_for(lambda r: _method(r) == "PUT" and r.status == 200)
        page.wait_for_selector("text=Saved")

        saved = _template_config(workspace_root, MULTIPLE_TEMPLATE)["placements"][0]
        deltas = {
            (round(after["x"] - before["x"]), round(after["y"] - before["y"]))
            for before, after in zip(original["bounding_box"], saved["bounding_box"], strict=True)
        }
        # Two single-pixel steps right, one fast step down.
        assert deltas == {(2, 8)}


# --- giving a folder of photos a kind ------------------------------------


class TestKindPickerCreatesEachKind:
    """The plan's explicit ask: browser automation validating that each kind
    can actually be *calibrated* from scratch, not just edited once it already
    has a template.yaml.

    A template is a folder of photos the user puts in the workspace -- the
    calibrator does not create them -- so these put the folder there and start
    where the calibrator starts: the kind picker taking over the workspace.
    """

    def _open_picker(self, page, workspace_root: Path, name: str, files: dict[str, Path]) -> None:  # noqa: ANN001
        folder = workspace_root / "mockup-templates" / name
        folder.mkdir()
        for filename, source in files.items():
            (folder / filename).write_bytes(source.read_bytes())
        page.reload()
        _select_template(page, name)
        page.wait_for_selector(".kind-picker")
        assert _selected_template(page) == name

    def _source(self, workspace_root: Path, colour: str = "black") -> Path:
        source = workspace_root / "mockup-templates" / COLOUR_MATRIX_TEMPLATE / f"{colour}.png"
        assert source.is_file()
        return source

    def test_one_photo_becomes_a_single_kind_template(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        self._open_picker(
            page, workspace_root, "lifestyle-01", {"black.png": self._source(workspace_root)}
        )

        page.get_by_role("radio", name="Single one photo, one garment").check()
        kind_log = TrafficLog(page, "/kind")
        page.get_by_role("button", name="Start calibrating →").click()
        kind_log.wait_for(lambda r: _method(r) == "POST" and r.status == 200)

        page.wait_for_selector(PREVIEW_IMAGE)
        page.wait_for_selector(HANDLE)
        assert page.get_by_role("button", name="Save template.yaml").count() == 0

        saved = _template_config(workspace_root, "lifestyle-01")
        assert saved["kind"] == "single"
        # PRD 28: a scene kind uses the fixed filename, so whatever the folder
        # called its photo is gone by now.
        assert (workspace_root / "mockup-templates" / "lifestyle-01" / "scene.png").is_file()
        assert not (workspace_root / "mockup-templates" / "lifestyle-01" / "black.png").exists()

    def test_a_single_kind_template_can_hide_its_placement_outline(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """One box, always selected: without the toggle there was no way to
        get the outline and its four handles off the artwork being judged."""
        self._open_picker(
            page, workspace_root, "lifestyle-02", {"black.png": self._source(workspace_root)}
        )
        page.get_by_role("button", name="Start calibrating →").click()
        page.wait_for_selector(HANDLE)

        page.get_by_label("show placement outline").uncheck()
        page.wait_for_function("() => document.querySelectorAll('.quad-editor__box').length === 0")
        assert page.locator(HANDLE).count() == 0

    def test_two_photos_become_a_colour_matrix_template(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        self._open_picker(
            page,
            workspace_root,
            "flat-lay-02",
            {
                "black.png": self._source(workspace_root),
                "ivory.png": self._source(workspace_root, "ivory"),
            },
        )

        # The picker reports what each filename will be taken as (PRD 7a)
        # before anything is committed.
        page.wait_for_selector(".kind-picker__file")
        listed = page.locator(".kind-picker__filename").all_inner_texts()
        assert sorted(listed) == ["black.png", "ivory.png"]

        kind_log = TrafficLog(page, "/kind")
        page.get_by_role("button", name="Start calibrating →").click()
        kind_log.wait_for(lambda r: _method(r) == "POST" and r.status == 200)

        _wait_for_colours(page, 2)
        assert sorted(_colours(page)) == ["black", "ivory"]

    def test_the_picker_warns_about_a_filename_that_is_not_a_slug(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """A photo called `Heather Grey.png` yields the colour `heather-grey`,
        which is not the name on disk. The picker says so before you commit,
        and `assign_kind` then renames the file to match (PRD 7a).

        Two photos, not one: a single-photo set cannot be a colour matrix at
        all now, so the report it belongs to is not on screen for one.
        """
        source = self._source(workspace_root)
        self._open_picker(
            page,
            workspace_root,
            "flat-lay-03",
            {"Heather Grey.png": source, "forest.png": source},
        )
        page.wait_for_selector(".kind-picker__warn")
        assert "not a colour slug" in page.locator(".kind-picker__warn").inner_text()

    def test_a_single_photo_cannot_be_a_colour_matrix(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        """One photo per colour, over one photo, is a matrix of one -- which is
        what `single` already is. Worse, it names the colour after the
        filename, so `photo.png` became a garment colour called "photo"."""
        self._open_picker(
            page,
            workspace_root,
            "flat-lay-04",
            {"just-the-one.png": self._source(workspace_root)},
        )

        colour_matrix = page.locator('.kind-picker input[value="colour-matrix"]')
        assert colour_matrix.is_disabled()
        assert page.locator('.kind-picker input[value="single"]').is_checked()
        # `multiple` is a chart: one photo with several garments in it, so it
        # is exactly the single-photo case and must stay offered.
        assert page.locator('.kind-picker input[value="multiple"]').is_enabled()

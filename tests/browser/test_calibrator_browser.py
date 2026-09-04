"""Browser tests for the calibrator, one flow per template kind.

These cover the one thing no other layer can: that the React app, the FastAPI
endpoints and the real render pipeline actually work *together* in a
browser -- a drag reaching the server, a PNG coming back, and Save writing
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


def _image_natural_size(page) -> list[int]:  # noqa: ANN001
    page.wait_for_function(
        "() => document.querySelector('img.quad-editor__image')?.naturalWidth > 0"
    )
    return page.evaluate(
        "() => { const i = document.querySelector('img.quad-editor__image');"
        "  return [i.naturalWidth, i.naturalHeight]; }"
    )


def test_calibrator_loads_the_workspace_templates(page) -> None:  # noqa: ANN001
    page.wait_for_selector(PREVIEW_IMAGE)
    assert page.locator("h1").inner_text() == "Mockup calibrator"
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
        page.wait_for_selector(".filmstrip__item")
        assert _selected_template(page) == COLOUR_MATRIX_TEMPLATE
        assert list(_image_natural_size(page)) == list(COLOUR_MATRIX_SIZE)


class TestColourMatrixKind:
    def test_filmstrip_lists_every_colour_in_the_template_set(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(".filmstrip__item")
        colours = page.locator(".filmstrip__item").all_inner_texts()
        assert colours == ["black", "blue-jean", "ivory", "moss"]

    def test_preview_renders_a_real_png_at_the_true_pixel_size(self, page) -> None:  # noqa: ANN001
        """The preview must be a real server render, not a client-side
        stand-in -- the proof is that the browser *decoded* the response at
        the synthetic template's real pixel size, which only the server-side
        pipeline knows."""
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        with page.expect_response(
            lambda r: "/preview" in r.url and r.status == 200
        ) as response_info:
            page.reload()
            _select_template(page, COLOUR_MATRIX_TEMPLATE)
        assert response_info.value.headers["content-type"] == "image/png"
        assert list(_image_natural_size(page)) == list(COLOUR_MATRIX_SIZE)

    def test_selecting_a_colour_rerenders_that_colour(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(".filmstrip__item")
        with page.expect_response(lambda r: "/preview" in r.url and r.status == 200):
            page.locator(".filmstrip__item", has_text="moss").click()
        assert "filmstrip__item--active" in (
            page.locator(".filmstrip__item", has_text="moss").get_attribute("class") or ""
        )

    def test_gallery_shows_a_thumbnail_per_colour(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(".gallery__item")
        assert page.locator(".gallery__item").count() == 4

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
        with page.expect_request(lambda r: "/preview" in r.url) as request_info:
            page.get_by_label("Follow fabric wrinkles").check()
        sent = json.loads(request_info.value.post_data or "{}")
        assert sent["displace"]["enabled"] is True

    def test_the_shading_presets_write_a_blend_mode(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        with page.expect_request(lambda r: "/preview" in r.url) as request_info:
            page.get_by_role("button", name="Rich").click()
        sent = json.loads(request_info.value.post_data or "{}")
        assert sent["shade"]["blend"] == "multiply"

    def test_choosing_a_test_design_rerenders_against_it(self, page) -> None:  # noqa: ANN001
        _select_template(page, COLOUR_MATRIX_TEMPLATE)
        page.wait_for_selector(PREVIEW_IMAGE)
        with page.expect_request(lambda r: "/preview" in r.url) as request_info:
            page.get_by_label("Test design").select_option("bundled-on-dark")
        sent = json.loads(request_info.value.post_data or "{}")
        assert sent["design"] == "bundled-on-dark"

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

        with page.expect_response(lambda r: "/config" in r.url and r.request.method == "PUT"):
            page.get_by_role("button", name="Save template.yaml").click()
        page.wait_for_selector("text=saved")

        saved = _template_config(workspace_root, COLOUR_MATRIX_TEMPLATE)
        assert saved["kind"] == "colour-matrix"
        assert saved["bounding_box"] != original
        assert len(saved["bounding_box"]) == 4


# --- multiple kind -------------------------------------------------------


class TestMultipleKind:
    def test_placements_panel_lists_every_placement(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".placements-panel__item")
        assert page.locator(".placements-panel__item").count() == 2

    def test_preview_is_the_full_composite_at_the_scene_pixel_size(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        with page.expect_response(
            lambda r: "/preview" in r.url and r.status == 200
        ) as response_info:
            page.reload()
            _select_template(page, MULTIPLE_TEMPLATE)
        assert response_info.value.headers["content-type"] == "image/png"
        assert list(_image_natural_size(page)) == list(CHART_SIZE)

    def test_clicking_a_dimmed_box_selects_it(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        boxes = page.locator(".quad-editor__box")
        assert boxes.count() == 2
        boxes.nth(1).click()
        assert "placements-panel__item--active" in (
            page.locator(".placements-panel__item").nth(1).get_attribute("class") or ""
        )

    def test_duplicate_and_offset_adds_a_third_placement(self, page) -> None:  # noqa: ANN001
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".quad-editor__box")
        page.get_by_role("button", name="Duplicate & offset selected").click()
        assert page.locator(".placements-panel__item").count() == 3
        assert page.locator(".quad-editor__box").count() == 3

    def test_saving_writes_every_placement(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        _select_template(page, MULTIPLE_TEMPLATE)
        page.wait_for_selector(".placements-panel__item")
        page.get_by_role("button", name="Add placement").click()
        colour_inputs = page.locator(".placements-panel__item input").nth(-2)
        colour_inputs.fill("ivory")

        with page.expect_response(lambda r: "/config" in r.url and r.request.method == "PUT"):
            page.get_by_role("button", name="Save template.yaml").click()
        page.wait_for_selector("text=saved")

        saved = _template_config(workspace_root, MULTIPLE_TEMPLATE)
        assert saved["kind"] == "multiple"
        assert len(saved["placements"]) == 3
        assert saved["placements"][-1]["colour"] == "ivory"


# --- creating a new template through the upload flow ---------------------


class TestUploadCreatesEachKind:
    """The plan's explicit ask: browser automation validating that each kind
    can actually be *created* through the calibrator, not just edited once
    it already exists."""

    def test_uploading_a_single_photo_creates_a_single_kind_template(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        source = workspace_root / "mockup-templates" / COLOUR_MATRIX_TEMPLATE / "black.png"
        assert source.is_file()

        page.get_by_label("Name").fill("lifestyle-01")
        page.get_by_label("Kind").select_option("single")
        with page.expect_response(lambda r: r.url.endswith("/api/templates") and r.status == 200):
            page.locator(".upload-form input[type=file]").set_input_files(str(source))
        page.wait_for_selector("text=uploaded")

        assert _selected_template(page) == "lifestyle-01"
        page.wait_for_selector(HANDLE)

        with page.expect_response(lambda r: "/config" in r.url and r.request.method == "PUT"):
            page.get_by_role("button", name="Save template.yaml").click()

        saved = _template_config(workspace_root, "lifestyle-01")
        assert saved["kind"] == "single"
        assert (workspace_root / "mockup-templates" / "lifestyle-01" / "scene.png").is_file()

    def test_uploading_two_photos_creates_a_colour_matrix_template(  # noqa: ANN001
        self, page, workspace_root: Path
    ) -> None:
        base_dir = workspace_root / "mockup-templates" / COLOUR_MATRIX_TEMPLATE
        black = base_dir / "black.png"
        ivory = base_dir / "ivory.png"

        page.get_by_label("Name").fill("flat-lay-02")
        page.get_by_label("Kind").select_option("colour-matrix")
        with page.expect_response(lambda r: r.url.endswith("/api/templates") and r.status == 200):
            page.locator(".upload-form input[type=file]").set_input_files([str(black), str(ivory)])
        page.wait_for_selector("text=uploaded")

        assert _selected_template(page) == "flat-lay-02"
        page.wait_for_selector(".filmstrip__item")
        assert sorted(page.locator(".filmstrip__item").all_inner_texts()) == ["black", "ivory"]

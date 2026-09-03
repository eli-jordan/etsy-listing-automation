"""Browser tests for the calibrator.

These cover the one thing no other layer can: that the React app, the FastAPI
endpoints and the real render pipeline actually work *together* in a browser --
a quad drag reaching the server, a PNG coming back, and Save writing the
template.yaml that `apply` will later read.

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

TEMPLATE = "flat-lay-01"
HANDLE = "circle.quad-editor__handle"
PREVIEW_IMAGE = "img.quad-editor__image"

# The synthetic template set's pixel size (scripts/generate_test_assets.py).
TEMPLATE_WIDTH = 480
TEMPLATE_HEIGHT = 576


def _quad_from_disk(workspace_root: Path) -> list[list[float]]:
    config = yaml.safe_load(
        (workspace_root / "mockup-templates" / TEMPLATE / "template.yaml").read_text(
            encoding="utf-8"
        )
    )
    quad: list[list[float]] = config["warp"]["quad"]
    return quad


def test_calibrator_loads_the_workspace_templates(page) -> None:  # noqa: ANN001
    page.wait_for_selector(PREVIEW_IMAGE)
    assert page.locator("h1").inner_text() == "Mockup calibrator"
    assert TEMPLATE in page.locator("select[aria-label='Template']").inner_text()


def test_filmstrip_lists_every_colour_in_the_template_set(page) -> None:  # noqa: ANN001
    page.wait_for_selector(".filmstrip__item")
    colours = page.locator(".filmstrip__item").all_inner_texts()
    assert colours == ["black", "blue-jean", "ivory", "moss"]


def test_preview_renders_a_png_through_the_real_pipeline(page) -> None:  # noqa: ANN001
    """The preview must be a real server render, not a client-side stand-in.

    The proof is that the browser *decoded* the response: naturalWidth is only
    non-zero for an image it successfully parsed, and it matches the synthetic
    template's real pixel size, which only the server-side pipeline knows.
    """
    with page.expect_response(lambda r: "/preview" in r.url and r.status == 200) as response_info:
        page.reload()
    assert response_info.value.headers["content-type"] == "image/png"

    page.wait_for_selector(PREVIEW_IMAGE)
    assert (page.locator(PREVIEW_IMAGE).get_attribute("src") or "").startswith("blob:")

    page.wait_for_function(
        "() => document.querySelector('img.quad-editor__image')?.naturalWidth > 0"
    )
    dimensions = page.evaluate(
        "() => { const i = document.querySelector('img.quad-editor__image');"
        "  return [i.naturalWidth, i.naturalHeight]; }"
    )
    assert dimensions == [TEMPLATE_WIDTH, TEMPLATE_HEIGHT]


def test_selecting_a_colour_rerenders_that_colour(page) -> None:  # noqa: ANN001
    page.wait_for_selector(".filmstrip__item")

    with page.expect_response(lambda r: "/preview" in r.url and r.status == 200):
        page.locator(".filmstrip__item", has_text="moss").click()

    assert "filmstrip__item--active" in (
        page.locator(".filmstrip__item", has_text="moss").get_attribute("class") or ""
    )


def test_dragging_a_quad_handle_moves_it_and_rerenders(page) -> None:  # noqa: ANN001
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


def test_saving_writes_the_dragged_quad_to_template_yaml(  # noqa: ANN001
    page, workspace_root: Path
) -> None:
    """The full loop the calibrator exists for: drag, save, and the geometry is
    on disk in the file the render stage reads."""
    original_quad = _quad_from_disk(workspace_root)

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

    saved_quad = _quad_from_disk(workspace_root)
    assert saved_quad != original_quad
    assert len(saved_quad) == 4


def test_toggling_displace_rerenders_with_the_new_setting(page) -> None:  # noqa: ANN001
    page.wait_for_selector(PREVIEW_IMAGE)
    displace_toggle = page.locator("fieldset", has_text="Displace").locator("input[type=checkbox]")

    with page.expect_request(lambda r: "/preview" in r.url) as request_info:
        displace_toggle.check()

    sent = json.loads(request_info.value.post_data or "{}")
    assert sent["displace"]["enabled"] is True


def test_no_console_errors_on_load(page) -> None:  # noqa: ANN001
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.reload()
    page.wait_for_selector(PREVIEW_IMAGE)
    assert errors == []

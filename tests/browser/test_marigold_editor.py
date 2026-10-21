"""The live editor, durable queue and CPU renderer across every template kind."""

import base64
import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from tests.support.marigold import PreparationRuntime, PreparationWorker, marigold_template

pytestmark = pytest.mark.browser


@pytest.fixture(params=["single", "colour-matrix", "multiple"])
def template_kind(request):
    return request.param


@pytest.fixture
def preparation_runtime():
    return PreparationRuntime()


@pytest.fixture
def app_options(workspace_root: Path, template_kind, preparation_runtime):
    marigold_template(workspace_root, template_kind, name="marigold-shirt", renderer="photo-warp")
    return {"preparation_runtime": preparation_runtime}


def select_template(page):
    page.locator(".template-rail__item[data-template='marigold-shirt']").click()
    page.get_by_label("Renderer", exact=True).select_option("marigold")
    page.get_by_role("button", name="Prepare template", exact=True).wait_for()


def ready(page):
    page.wait_for_function(
        "() => document.querySelector('.mg-preparation .mg-status')?.textContent === 'Ready'"
    )


def test_edit_prepare_reconnect_mask_and_full_quality_preview(
    page, workspace_root: Path, template_kind, preparation_runtime
):
    select_template(page)
    origin = page.url.split("/templates")[0]
    assert page.get_by_role("button", name="Edit mask", exact=True).is_disabled()
    with page.expect_response(
        lambda r: (
            "/api/preparation/jobs" in r.url and r.request.method == "POST" and r.status == 202
        )
    ):
        page.get_by_role("button", name="Prepare template", exact=True).click()
    ready(page)
    calls = sum(len(worker.calls) for worker in preparation_runtime.workers)
    assert calls == 3
    state = page.request.get(origin + "/api/templates/marigold-shirt/preparation").json()
    assert all(p["mask_available"] for p in state["placements"])
    if template_kind == "multiple":
        assert [p["placement_id"] for p in state["placements"]] == ["left-shirt", "right-shirt"]
    else:
        assert [p["placement_id"] for p in state["placements"]] == [None]
    main = state["main_photo"]
    page.reload()
    page.locator(".template-rail__item[data-template='marigold-shirt']").click()
    ready(page)
    assert len(page.request.get(origin + "/api/preparation/jobs").json()) == 1
    assert sum(len(worker.calls) for worker in preparation_runtime.workers) == calls
    assert (
        page.request.get(origin + "/api/templates/marigold-shirt/preparation").json()["main_photo"]
        == main
    )
    page.get_by_role("button", name="Edit mask", exact=True).click()
    page.get_by_text("Red = hidden print", exact=True).wait_for()
    area = page.get_by_label("Mask drawing area")
    bounds = area.bounding_box()
    assert bounds is not None
    with page.expect_response(
        lambda r: r.url.endswith("/config") and r.request.method == "PUT" and r.status == 200
    ) as saved:
        page.mouse.move(bounds["x"] + bounds["width"] * 0.45, bounds["y"] + bounds["height"] * 0.45)
        page.mouse.down()
        page.mouse.move(
            bounds["x"] + bounds["width"] * 0.5, bounds["y"] + bounds["height"] * 0.5, steps=5
        )
        page.mouse.up()
        page.get_by_role("button", name="Done", exact=True).click()
    assert saved.value.request.post_data_json["mask_edits"][0]["operations"][0]["type"] == "stroke"
    assert not page.get_by_role("toolbar", name="Mask brushes").is_visible()
    ready(page)
    page.get_by_role("button", name="Edit mask", exact=True).click()
    page.evaluate("document.activeElement?.blur()")
    assert page.evaluate("document.activeElement === document.body")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Edit mask", exact=True).wait_for()
    assert not page.get_by_role("toolbar", name="Mask brushes").is_visible()
    mask_url = (
        "/api/templates/marigold-shirt/placements/left-shirt/mask"
        if template_kind == "multiple"
        else "/api/templates/marigold-shirt/mask"
    )
    raster = Image.open(BytesIO(page.request.get(origin + mask_url).body()))
    assert raster.size == (64, 64)
    assert raster.getpixel((30, 30)) == 0
    page.get_by_role("tab", name="Preview", exact=True).click()
    count = 2 if template_kind == "colour-matrix" else 1
    page.wait_for_function(
        "(n) => document.querySelectorAll('.preview-grid__tile img').length === n", arg=count
    )
    page.locator(".preview-grid__open").first.click()
    page.wait_for_function("() => document.querySelector('.lightbox__image')?.naturalWidth === 64")
    page.keyboard.press("Escape")
    page.get_by_role("tab", name="Calibrate", exact=True).click()
    page.get_by_role("slider", name="Fabric texture").press("ArrowRight")
    page.get_by_role("tab", name="Preview", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('.preview-grid__actions .btn-danger') !== null"
    )
    assert page.locator(".preview-grid__tile img").count() == count
    assert sum(len(worker.calls) for worker in preparation_runtime.workers) == calls


def test_cancel_survives_reconnect_and_requires_explicit_restart(page, preparation_runtime):
    def blocked_worker(root):
        worker = PreparationWorker(root)
        worker.release.clear()
        return worker

    preparation_runtime.factory = blocked_worker
    select_template(page)
    origin = page.url.split("/templates")[0]
    page.get_by_role("button", name="Prepare template", exact=True).click()
    page.get_by_role("button", name="Cancel preparation", exact=True).wait_for()
    page.reload()
    page.locator(".template-rail__item[data-template=marigold-shirt]").click()
    page.get_by_role("button", name="Cancel preparation", exact=True).click()
    for worker in preparation_runtime.workers:
        worker.release.set()
    page.get_by_role("button", name="Prepare template", exact=True).wait_for()
    jobs = page.request.get(origin + "/api/preparation/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["phase"] == "cancelled"
    page.reload()
    page.locator(".template-rail__item[data-template=marigold-shirt]").click()
    page.get_by_role("button", name="Prepare template", exact=True).wait_for()
    assert len(page.request.get(origin + "/api/preparation/jobs").json()) == 1


def test_failed_preparation_has_actionable_error_and_explicit_retry(page, preparation_runtime):
    def failed_worker(root):
        worker = PreparationWorker(root)
        worker.failure = RuntimeError("Controlled prediction failure")
        return worker

    preparation_runtime.factory = failed_worker
    select_template(page)
    page.get_by_role("button", name="Prepare template", exact=True).click()
    page.get_by_role("button", name="Retry preparation", exact=True).wait_for()
    page.get_by_text("Controlled prediction failure", exact=False).wait_for()
    for worker in preparation_runtime.workers:
        worker.failure = None
    preparation_runtime.factory = PreparationWorker
    page.get_by_role("button", name="Retry preparation", exact=True).click()
    ready(page)
    origin = page.url.split("/templates")[0]
    jobs = page.request.get(origin + "/api/preparation/jobs").json()
    assert len(jobs) == 2
    assert {job["phase"] for job in jobs} == {"failed", "completed"}


def test_changed_photo_recovers_only_after_explicit_reset_and_prepare(
    page, workspace_root: Path, preparation_runtime
):
    from etsy_listings.core.workspace import Workspace

    select_template(page)
    with page.expect_response(
        lambda r: (
            "/api/preparation/jobs" in r.url and r.request.method == "POST" and r.status == 202
        )
    ):
        page.get_by_role("button", name="Prepare template", exact=True).click()
    ready(page)
    origin = page.url.split("/templates")[0]
    prepared = page.request.get(origin + "/api/templates/marigold-shirt/preparation").json()
    assert prepared["maps"]["state"] == "ready"
    assert prepared["latest_job"]["phase"] == "completed"
    assert all(placement["mask_available"] for placement in prepared["placements"])
    calls = sum(len(worker.calls) for worker in preparation_runtime.workers)
    workspace = Workspace.discover(root_override=workspace_root)
    photo = workspace.template_main_photo("marigold-shirt")
    with Image.open(photo) as source:
        changed = source.convert("RGB")
    changed.putpixel((30, 30), (17, 23, 41))
    changed.save(photo)
    page.reload()
    page.locator(".template-rail__item[data-template=marigold-shirt]").click()
    recovery = page.get_by_role("button", name="Reset masks and prepare", exact=True)
    try:
        recovery.wait_for()
    except Exception as exc:
        origin = page.url.split("/templates")[0]
        status = page.request.get(origin + "/api/templates/marigold-shirt/preparation").text()
        raise AssertionError(status + "\n" + page.locator("body").inner_text()) from exc
    assert page.get_by_role("button", name="Edit mask", exact=True).is_disabled()
    assert sum(len(worker.calls) for worker in preparation_runtime.workers) == calls
    with page.expect_response(
        lambda r: (
            "/api/preparation/jobs" in r.url and r.request.method == "POST" and r.status == 202
        )
    ) as submitted:
        recovery.click()
    assert submitted.value.request.post_data_json["reset_masks_for_photo"] is True
    assert submitted.value.request.post_data_json["action"] == "prepare_again"
    ready(page)
    assert page.get_by_role("button", name="Edit mask", exact=True).is_enabled()
    assert sum(len(worker.calls) for worker in preparation_runtime.workers) == calls + 3


def test_first_prepare_mask_save_needs_no_reload_and_external_edit_still_conflicts(
    page, preparation_runtime
):
    select_template(page)
    origin = page.url.split("/templates")[0]
    page.get_by_role("button", name="Prepare template", exact=True).click()
    ready(page)

    def stroke():
        area = page.get_by_label("Mask drawing area").bounding_box()
        assert area is not None
        page.mouse.move(area["x"] + area["width"] * 0.45, area["y"] + area["height"] * 0.45)
        page.mouse.down()
        page.mouse.move(area["x"] + area["width"] * 0.5, area["y"] + area["height"] * 0.5, steps=5)
        page.mouse.up()

    page.get_by_role("button", name="Edit mask", exact=True).click()
    with page.expect_response(
        lambda r: r.url.endswith("/config") and r.request.method == "PUT" and r.status == 200
    ):
        stroke()
    page.get_by_role("button", name="Done", exact=True).click()
    ready(page)
    calls = sum(len(worker.calls) for worker in preparation_runtime.workers)
    assert calls == 3

    page.get_by_role("tab", name="Preview", exact=True).click()
    expected = (
        2
        if page.request.get(origin + "/api/templates/marigold-shirt/config").json()["kind"]
        == "colour-matrix"
        else 1
    )
    page.wait_for_function(
        "(n) => document.querySelectorAll('.preview-grid__tile img').length === n", arg=expected
    )
    page.get_by_role("tab", name="Calibrate", exact=True).click()

    config_url = origin + "/api/templates/marigold-shirt/config"
    document = page.request.get(config_url)
    config = document.json()
    config["renderer"]["config"]["appearance"]["fabric_texture"] = 0.33
    external = page.request.put(
        config_url,
        headers={"If-Match": document.headers["etag"]},
        data={"request_id": "external-edit", "config": config},
    )
    assert external.status == 200
    page.get_by_role("button", name="Edit mask", exact=True).click()
    with page.expect_response(
        lambda r: r.url.endswith("/config") and r.request.method == "PUT" and r.status == 412
    ):
        stroke()
    page.get_by_role("button", name="Reload template", exact=True).wait_for()
    assert page.get_by_role("toolbar", name="Mask brushes").is_visible()
    assert page.request.get(config_url).headers["etag"] == external.headers["etag"]
    assert sum(len(worker.calls) for worker in preparation_runtime.workers) == calls


def test_renderer_switch_keeps_the_same_centered_canvas_size(page):
    page.set_viewport_size({"width": 2000, "height": 1100})
    page.locator(".template-rail__item[data-template='marigold-shirt']").click()
    photo = page.get_by_alt_text("Rendered preview")
    photo.wait_for()
    page.wait_for_function("() => document.querySelector('.quad-editor__image')?.naturalWidth > 0")
    before = page.locator(".app").bounding_box()
    photo_before = photo.bounding_box()
    assert before is not None and photo_before is not None
    page.get_by_label("Renderer", exact=True).select_option("marigold")
    page.get_by_role("button", name="Prepare template", exact=True).wait_for()
    after = page.locator(".app").bounding_box()
    photo_after = photo.bounding_box()
    assert after is not None and photo_after is not None
    assert after["width"] == pytest.approx(before["width"], abs=1)
    assert after["x"] == pytest.approx(before["x"], abs=1)
    assert photo_after["width"] == pytest.approx(photo_before["width"], abs=1)


def test_new_tab_reads_current_renderer_and_can_prepare_after_an_external_save(
    page, workspace_root
):
    import os
    import time

    from etsy_listings.core.workspace import Workspace

    workspace = Workspace.discover(root_override=workspace_root)
    path = workspace.template_config_file("marigold-shirt")
    old = time.time() - 86400
    os.utime(path, (old, old))
    page.locator(".template-rail__item[data-template='marigold-shirt']").click()
    assert page.get_by_label("Renderer", exact=True).input_value() == "photo-warp"
    origin = page.url.split("/templates")[0]
    url = origin + "/api/templates/marigold-shirt/config"
    loaded = page.request.get(url)
    config = loaded.json()
    config["renderer"] = {"type": "marigold", "config": {}}
    saved = page.request.put(
        url,
        headers={"If-Match": loaded.headers["etag"]},
        data={"request_id": "external-renderer-switch", "config": config},
    )
    assert saved.status == 200
    other = page.context.new_page()
    other.goto(origin + "/templates")
    other.locator(".template-rail__item[data-template='marigold-shirt']").click()
    renderer = other.get_by_label("Renderer", exact=True)
    renderer.wait_for()
    assert renderer.input_value() == "marigold"
    with other.expect_response(
        lambda r: "/api/preparation/jobs" in r.url and r.request.method == "POST"
    ) as submitted:
        other.get_by_role("button", name="Prepare template", exact=True).click()
    assert submitted.value.status == 202, submitted.value.text()
    ready(other)
    # The first tab still has a genuinely stale edit and must not overwrite it.
    with page.expect_response(
        lambda r: r.url.endswith("/config") and r.request.method == "PUT"
    ) as refused:
        page.get_by_label("Renderer", exact=True).select_option("marigold")
    assert refused.value.status == 412
    page.get_by_role("button", name="Reload template", exact=True).wait_for()


@pytest.mark.parametrize("template_kind", ["colour-matrix"], indirect=True)
def test_colour_selection_changes_fallback_and_prepared_composite_without_saving(
    page, preparation_runtime
):
    with page.expect_response(
        lambda r: r.url.endswith("/config") and r.request.method == "PUT" and r.status == 200
    ):
        select_template(page)
    origin = page.url.split("/templates")[0]
    config_url = origin + "/api/templates/marigold-shirt/config"
    before = page.request.get(config_url).headers["etag"]
    main = page.request.get(origin + "/api/templates/marigold-shirt/preparation").json()[
        "main_photo"
    ]
    selector = page.get_by_role("combobox", name="Colour", exact=True)
    for colour in ["navy", "ivory"]:
        selector.select_option(colour)
        page.wait_for_function(
            "(colour) => document.querySelector('.quad-editor__image')"
            "?.src.endsWith('/photo?colour=' + colour)",
            arg=colour,
        )
    assert page.request.get(config_url).headers["etag"] == before
    assert not preparation_runtime.workers
    page.get_by_role("button", name="Prepare template", exact=True).click()
    ready(page)
    prepared = page.request.get(config_url).headers["etag"]
    calls = sum(len(worker.calls) for worker in preparation_runtime.workers)
    for colour, rgb in [("navy", [0, 0, 128]), ("ivory", [255, 255, 240])]:
        with page.expect_response(
            lambda r, colour=colour: (
                "/preview?scale=editor" in r.url
                and r.request.post_data_json.get("colour") == colour
                and r.status == 200
            )
        ):
            selector.select_option(colour)
        page.wait_for_function(
            """(rgb) => {
              const image = document.querySelector('.quad-editor__image');
              if (!image?.src.startsWith('blob:') || !image.complete) return false;
              if (!image.naturalWidth) return false;
              const canvas = document.createElement('canvas');
              canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
              const ctx = canvas.getContext('2d'); ctx.drawImage(image, 0, 0);
              const pixel = ctx.getImageData(canvas.width * 0.15, canvas.height * 0.15, 1, 1).data;
              return rgb.every((v, i) => Math.abs(v - pixel[i]) < 12);
            }""",
            arg=rgb,
            timeout=5000,
        )
    assert page.request.get(config_url).headers["etag"] == prepared
    assert sum(len(worker.calls) for worker in preparation_runtime.workers) == calls
    assert (
        page.request.get(origin + "/api/templates/marigold-shirt/preparation").json()["main_photo"]
        == main
    )


def test_renderer_switch_renders_before_autosave_and_discards_inflight_frame(page):
    from playwright.sync_api import expect

    select_template(page)
    page.get_by_role("button", name="Prepare template", exact=True).click()
    ready(page)
    page.wait_for_function(
        "() => document.querySelector('.quad-editor__image')?.src.startsWith('blob:')"
    )
    held = []

    def hold_material(route):
        if not held and route.request.post_data_json["renderer"]["type"] == "marigold":
            held.append((route, route.fetch()))
        else:
            route.continue_()

    page.route("**/preview?scale=editor", hold_material)
    texture = page.get_by_role("slider", name="Fabric texture")
    texture.press("ArrowRight")
    edited_texture = texture.input_value()
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(held) == 1
    with page.expect_response(
        lambda r: (
            r.url.endswith("/config")
            and r.request.method == "PUT"
            and r.request.post_data_json["config"]["renderer"]["type"] == "photo-warp"
            and r.status == 200
        )
    ):
        with page.expect_response(
            lambda r: (
                "/preview?scale=editor" in r.url
                and r.request.post_data_json["renderer"]["type"] == "photo-warp"
            )
        ) as rendered:
            page.get_by_label("Renderer", exact=True).select_option("photo-warp")
        assert rendered.value.status == 200
        canvas = page.get_by_alt_text("Rendered preview")
        expect(canvas).to_be_visible()
        pixels = canvas.evaluate("""async image => {
            await image.decode();
            const c = document.createElement('canvas');
            c.width = image.naturalWidth; c.height = image.naturalHeight;
            c.getContext('2d').drawImage(image, 0, 0);
            return c.toDataURL('image/png').split(',')[1];
        }""")
        image = Image.open(BytesIO(base64.b64decode(pixels)))
        image.load()
        assert image.size == (64, 64)
        photo_url = page.url.split("/templates")[0] + "/api/templates/marigold-shirt/photo"
        colour = rendered.value.request.post_data_json.get("colour")
        source = Image.open(
            BytesIO(page.request.get(photo_url, params={"colour": colour} if colour else {}).body())
        ).convert("RGB")
        artwork_difference = ImageChops.difference(image.convert("RGB"), source)
        assert artwork_difference.point(lambda v: 255 if v > 30 else 0).getbbox() is not None
    origin = page.url.split("/templates")[0]
    page.wait_for_function(
        "() => document.querySelector('.app__status')?.textContent.includes('Saved')"
    )
    config = page.request.get(origin + "/api/templates/marigold-shirt/config").json()
    assert config["renderer"]["type"] == "photo-warp"
    page.get_by_role("tab", name="Preview", exact=True).click()
    page.locator(".preview-grid__tile img").first.wait_for()
    page.get_by_role("tab", name="Calibrate", exact=True).click()
    with page.expect_response(
        lambda r: (
            r.url.endswith("/config")
            and r.request.method == "PUT"
            and r.request.post_data_json["config"]["renderer"]["type"] == "marigold"
            and r.status == 200
        )
    ):
        page.get_by_label("Renderer", exact=True).select_option("marigold")
    ready(page)
    page.wait_for_function(
        "() => document.querySelector('.quad-editor__image')?.src.startsWith('blob:')"
    )
    expect(page.get_by_role("slider", name="Fabric texture")).to_have_value(edited_texture)
    latest = page.get_by_alt_text("Rendered preview")
    latest.evaluate("image => image.decode()")
    current_source = latest.get_attribute("src")
    for route, response in held:
        route.fulfill(response=response)
    page.unroute("**/preview?scale=editor", hold_material)
    expect(latest).to_have_attribute("src", current_source)
    assert (
        page.request.get(origin + "/api/templates/marigold-shirt/config").json()["renderer"]["type"]
        == "marigold"
    )


@pytest.mark.parametrize("device_scale", [1, 2])
def test_mask_cursor_matches_photo_brush_on_hover_paint_and_resize(
    browser_type, calibrator_server, device_scale, template_kind
):
    from playwright.sync_api import expect

    context = browser_type.new_context(
        viewport={"width": 1280, "height": 900}, device_scale_factor=device_scale
    )
    cursor_page = context.new_page()
    try:
        cursor_page.goto(calibrator_server + "/templates")
        select_template(cursor_page)
        cursor_page.get_by_role("button", name="Prepare template", exact=True).click()
        ready(cursor_page)
        cursor_page.get_by_role("button", name="Edit mask", exact=True).click()
        area = cursor_page.get_by_label("Mask drawing area")
        cursor = cursor_page.get_by_label("Brush footprint", exact=True)
        dock = cursor_page.get_by_role("toolbar", name="Mask brushes")
        expect(dock.get_by_role("button", name="Undo brush stroke")).to_be_disabled()
        expect(dock.get_by_role("button", name="Reset mask")).to_be_enabled()
        mask_path = (
            "/api/templates/marigold-shirt/placements/left-shirt/mask"
            if template_kind == "multiple"
            else "/api/templates/marigold-shirt/mask"
        )

        def saved_mask():
            return Image.open(
                BytesIO(cursor_page.request.get(calibrator_server + mask_path).body())
            ).convert("L")

        for width, mode, diameter in [(1280, "Mask", 24), (1500, "Unmask", 40)]:
            cursor_page.set_viewport_size({"width": width, "height": 900})
            dock.get_by_role("button", name=mode, exact=True).click()
            dock.get_by_role("slider", name="Brush size").fill(str(diameter))
            bounds = area.bounding_box()
            assert bounds is not None
            x = bounds["x"] + bounds["width"] * 0.45
            y = bounds["y"] + bounds["height"] * 0.45
            if mode == "Unmask":
                # Give Unmask a fully excluded region so its entire footprint
                # becomes visible in saved pixels, independent of the prior stroke.
                dock.get_by_role("button", name="Mask", exact=True).click()
                dock.get_by_role("slider", name="Brush size").fill("80")
                with cursor_page.expect_response(
                    lambda r: (
                        r.url.endswith("/config") and r.request.method == "PUT" and r.status == 200
                    )
                ):
                    cursor_page.mouse.click(x, y)
                dock.get_by_role("button", name=mode, exact=True).click()
                dock.get_by_role("slider", name="Brush size").fill(str(diameter))
            before_mask = saved_mask()
            cursor_page.mouse.move(x, y)
            expect(cursor).to_be_visible()
            circle = cursor.locator("circle").last.bounding_box()
            assert circle is not None
            assert circle["width"] == pytest.approx(bounds["width"] * diameter / 64, abs=1.1)
            assert circle["height"] == pytest.approx(bounds["height"] * diameter / 64, abs=1.1)
            assert circle["x"] + circle["width"] / 2 == pytest.approx(x, abs=1)
            assert circle["y"] + circle["height"] / 2 == pytest.approx(y, abs=1)
            cursor_page.mouse.down()
            cursor_page.mouse.move(x + 8, y + 6, steps=3)
            painted = cursor.bounding_box()
            assert painted is not None
            assert painted["x"] + painted["width"] / 2 == pytest.approx(x + 8, abs=1)
            assert painted["y"] + painted["height"] / 2 == pytest.approx(y + 6, abs=1)
            dock.get_by_role("slider", name="Brush size").fill(str(diameter + 8))
            active_circle = cursor.locator("circle").last.bounding_box()
            assert active_circle is not None
            assert active_circle["width"] == pytest.approx(circle["width"], abs=1)
            with cursor_page.expect_response(
                lambda r: (
                    r.url.endswith("/config") and r.request.method == "PUT" and r.status == 200
                )
            ):
                cursor_page.mouse.up()
            changed = ImageChops.difference(before_mask, saved_mask()).getbbox()
            assert changed is not None
            # Compare the decoded raster footprint with the circle in screen
            # units. Allow the mask rasterizer's pixel rounding at both edges.
            assert (changed[2] - changed[0]) * bounds["width"] / 64 == pytest.approx(
                circle["width"] + 8, abs=3 * bounds["width"] / 64
            )
            assert (changed[3] - changed[1]) * bounds["height"] / 64 == pytest.approx(
                circle["height"] + 6, abs=3 * bounds["height"] / 64
            )
            expect(dock.get_by_role("button", name="Undo brush stroke")).to_be_enabled()
            cursor_page.mouse.move(bounds["x"] - 10, bounds["y"] - 10)
            expect(cursor).not_to_be_visible()
        cursor_page.get_by_role("button", name="Done", exact=True).click()
        expect(cursor).to_have_count(0)
        cursor_page.get_by_role("button", name="Edit mask", exact=True).click()
        expect(cursor).not_to_be_visible()
        cursor_page.keyboard.press("Escape")
        expect(dock).to_have_count(0)
    finally:
        context.close()


@pytest.mark.parametrize("template_kind", ["single"], indirect=True)
def test_mask_toolbar_keeps_direct_actions_reachable_on_mobile(page):
    from playwright.sync_api import expect

    select_template(page)
    page.get_by_role("button", name="Prepare template", exact=True).click()
    ready(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Edit mask", exact=True).click()
    dock = page.get_by_role("toolbar", name="Mask brushes")
    preview = page.locator(".app__preview").bounding_box()
    assert preview is not None
    for name in ["Mask", "Unmask", "Undo brush stroke", "Reset mask"]:
        action = dock.get_by_role("button", name=name, exact=True)
        expect(action).to_be_visible()
        box = action.bounding_box()
        assert box is not None
        assert preview["x"] <= box["x"]
        assert box["x"] + box["width"] <= preview["x"] + preview["width"]
    dock.get_by_role("button", name="Unmask", exact=True).click()
    expect(dock.get_by_role("button", name="Unmask", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    dock.get_by_role("button", name="Reset mask", exact=True).click()
    page.get_by_role("button", name="Done", exact=True).click()
    expect(dock).to_have_count(0)

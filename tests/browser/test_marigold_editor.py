"""The live editor, durable queue and CPU renderer across every template kind."""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

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

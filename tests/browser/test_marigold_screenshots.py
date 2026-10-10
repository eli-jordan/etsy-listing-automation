"""Capture approved states through the built editor, real queue and CPU renderer."""

import os
from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.workspace import remove_tree

from tests.support.marigold import PreparationRuntime, PreparationWorker, marigold_template

pytestmark = pytest.mark.browser
ASSETS = Path(__file__).resolve().parents[2] / "src/ui/design/assets/template-cards"


@pytest.fixture
def preparation_runtime():
    return PreparationRuntime()


@pytest.fixture
def app_options(workspace_root: Path, preparation_runtime):
    workspace = Workspace.discover(root_override=workspace_root)
    for name in workspace.template_names(include_uncalibrated=True):
        remove_tree(workspace.template_dir(name))
    for name, kind in [("hanging-on-fence", "colour-matrix"), ("two-shirt-scene", "multiple")]:
        marigold_template(workspace_root, kind, name=name)
        config = workspace.load_template_config(name).model_dump(mode="json")
        folder = workspace.template_dir(name)
        for photo in folder.glob("*.png"):
            photo.unlink()
        if kind == "colour-matrix":
            for colour in ["bay", "berry"]:
                Image.open(ASSETS / f"fence-{colour}.jpg").save(folder / f"{colour}.png")
            boxes = [[(177, 142), (305, 142), (305, 304), (177, 304)]]
        else:
            first = Image.open(ASSETS / "folded-ivory.jpg").convert("RGB")
            second = Image.open(ASSETS / "folded-yam.jpg").convert("RGB")
            pair = Image.new("RGB", (first.width * 2, first.height))
            pair.paste(first)
            pair.paste(second, (first.width, 0))
            pair.save(folder / "scene.png")
            boxes = [
                [(132, 188), (335, 188), (335, 382), (132, 382)],
                [(588, 188), (791, 188), (791, 382), (588, 382)],
            ]
        targets = config["placements"] if kind == "multiple" else [config]
        for target, box in zip(targets, boxes, strict=True):
            target["bounding_box"] = [{"x": x, "y": y} for x, y in box]
        workspace.save_template_config(name, load_template_config(config))
    return {"preparation_runtime": preparation_runtime}


def select(page, name):
    page.locator(f".template-rail__item[data-template='{name}']").click()


def ready(page):
    page.wait_for_function(
        "() => document.querySelector('.mg-preparation .mg-status')?.textContent === 'Ready'"
    )


def test_capture_approved_marigold_states(page, tmp_path: Path, preparation_runtime):
    page.set_viewport_size({"width": 1280, "height": 800})
    destination = Path(os.environ.get("MARIGOLD_SCREENSHOT_DIR", str(tmp_path / "screenshots")))
    destination.mkdir(parents=True, exist_ok=True)

    def shot(state):
        page.screenshot(path=str(destination / f"app-{state}.png"), animations="disabled")
        assert Image.open(destination / f"app-{state}.png").size == (1280, 800)

    select(page, "hanging-on-fence")
    page.get_by_role("button", name="Prepare template", exact=True).wait_for()
    assert (
        page.locator(".mg-preparation h3").evaluate("el => getComputedStyle(el).fontSize") == "10px"
    )
    assert page.locator(".template-rail").get_by_text("Needs calibration", exact=False).count() == 0
    tabs = page.get_by_role("tablist").bounding_box()
    picker = page.get_by_label("Test design", exact=True).bounding_box()
    assert tabs is not None and picker is not None
    assert abs(tabs["y"] - picker["y"]) < 8
    assert page.locator(".app__header").bounding_box()["height"] < 65
    shot("edit")
    page.get_by_role("button", name="About Light & shadow strength", exact=True).click()
    shot("realism-help")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Advanced settings", exact=False).click()
    page.get_by_role("dialog").wait_for()
    shot("inference-settings")
    page.keyboard.press("Escape")

    def blocked_worker(root):
        worker = PreparationWorker(root)
        worker.release.clear()
        return worker

    def failed_worker(root):
        worker = PreparationWorker(root)
        worker.failure = RuntimeError("Preparation stopped. Check the runtime, then retry.")
        return worker

    preparation_runtime.factory = failed_worker
    page.get_by_role("button", name="Prepare template", exact=True).click()
    page.get_by_role("button", name="Retry preparation", exact=True).wait_for()
    page.wait_for_function(
        "() => document.querySelector('.template-rail__item--active .mg-rail-state')"
        "?.textContent === 'Failed'"
    )
    shot("failed")
    for worker in preparation_runtime.workers:
        worker.failure = None
        worker.release.clear()
    preparation_runtime.factory = blocked_worker
    page.get_by_role("button", name="Retry preparation", exact=True).click()
    page.get_by_role("button", name="Cancel preparation", exact=True).wait_for()
    page.locator(".mg-queue-entry").wait_for()
    page.wait_for_function(
        "() => document.querySelector('.template-rail__item--active .mg-rail-state')"
        "?.textContent === 'Preparing'"
    )
    page.get_by_text("Estimating surface direction", exact=True).wait_for()
    shot("preparing")
    for worker in preparation_runtime.workers:
        worker.release.set()
    preparation_runtime.factory = PreparationWorker
    ready(page)
    page.get_by_role("button", name="Edit mask", exact=True).click()
    area = page.get_by_label("Mask drawing area").bounding_box()
    assert area is not None
    page.mouse.move(area["x"] + area["width"] * 0.45, area["y"] + area["height"] * 0.4)
    page.mouse.down()
    page.mouse.move(area["x"] + area["width"] * 0.52, area["y"] + area["height"] * 0.48, steps=8)
    page.mouse.up()
    shot("mask-editing")
    page.get_by_role("button", name="Done", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('.app__status')?.textContent.includes('Saved')"
    )
    ready(page)
    page.get_by_role("tab", name="Preview", exact=True).click()
    page.wait_for_function(
        "() => document.querySelectorAll('.preview-grid__tile img').length === 2"
    )
    shot("preview")
    page.get_by_role("tab", name="Calibrate", exact=True).click()
    page.get_by_role("slider", name="Fabric texture").press("ArrowRight")
    page.get_by_role("tab", name="Preview", exact=True).click()
    page.locator(".preview-grid__actions .btn-danger").wait_for()
    shot("outdated")

    select(page, "two-shirt-scene")
    for worker in preparation_runtime.workers:
        worker.release.clear()
    preparation_runtime.factory = blocked_worker
    page.get_by_role("button", name="Prepare template", exact=True).click()
    page.get_by_role("button", name="Cancel preparation", exact=True).wait_for()
    page.locator(".mg-queue-entry").wait_for()
    shot("multiple")
    for worker in preparation_runtime.workers:
        worker.release.set()
    ready(page)
    assert len(list(destination.glob("app-*.png"))) == 9

"""Measure real edit-to-decoded-preview latency in an isolated prepared workspace.

No model inference is permitted. The source is copied, never opened for writing.
Use a new output directory for each comparison. Prepared real photos remain external.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import statistics
import subprocess
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import uvicorn
from PIL import Image
from PIL import __version__ as pillow_version
from playwright.sync_api import Page, Request, Response, sync_playwright

from etsy_listings.core.preparation.runtime import Capability
from etsy_listings.core.workspace import Workspace
from etsy_listings.server.api.app import create_app

FINGERPRINT_JS = """async img => {
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const context = c.getContext('2d'); context.drawImage(img, 0, 0);
  const pixels = context.getImageData(0, 0, c.width, c.height).data;
  const digest = await crypto.subtle.digest('SHA-256', pixels);
  return Array.from(new Uint8Array(digest))
    .map(x => x.toString(16).padStart(2, '0')).join('');
}"""
DECODE_JS = """async img => {
  await img.decode();
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return {width: img.naturalWidth, height: img.naturalHeight};
}"""
PIXEL_JS = """(img, point) => {
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const context = c.getContext('2d'); context.drawImage(img, 0, 0);
  const bounds = img.getBoundingClientRect();
  const x = Math.floor((point.x - bounds.x) / bounds.width * c.width);
  const y = Math.floor((point.y - bounds.y) / bounds.height * c.height);
  return Array.from(context.getImageData(x, y, 1, 1).data).slice(0, 3);
}"""


class EvidenceOnlyRuntime:
    def inspect(self) -> Capability:
        return Capability(False, "Benchmark forbids model inference")

    def selection(self, version: str, *, installation_id: str | None = None) -> Capability:
        raise AssertionError("Benchmark must not select a model")

    def worker(self, selected: Capability, *, cache_root: Path) -> Any:
        raise AssertionError("Benchmark must never run model inference")


def measure(
    page: Page,
    name: str,
    kind: str,
    repeat: int,
    output: Path,
    checkpoints: list[tuple[str, str, float]],
    interactive: bool = False,
    during_rebuild: bool = False,
) -> dict[str, Any]:
    page.get_by_role("tab", name="Calibrate", exact=True).click()
    polygon = page.locator(".quad-editor__polygon").first
    bounds = polygon.bounding_box()
    assert bounds
    page.mouse.click(bounds["x"] + bounds["width"] * 0.07, bounds["y"] + bounds["height"] * 0.45)
    if interactive:
        page.wait_for_function(
            """() => {
                const i=document.querySelector('.quad-editor img');
                return i && i.src.startsWith('blob:') && i.complete && i.naturalWidth === 256;
            }"""
        )
    old_editor_source = page.get_by_alt_text("Rendered preview").first.get_attribute("src")
    old_fingerprint = (
        page.get_by_alt_text("Rendered preview").first.evaluate(FINGERPRINT_JS)
        if interactive
        else None
    )
    initial_preparation = page.evaluate(
        "async name => (await fetch('/api/templates/' + encodeURIComponent(name) + "
        "'/preparation')).json()",
        name,
    )
    before_pixel = None
    point = None
    spans = []
    start = None
    feedback = None
    preparation_responses = []
    saved_revision = None

    def response(r: Response) -> None:
        nonlocal saved_revision
        if r.request.method == "PUT" and r.url.endswith("/config"):
            saved_revision = r.headers.get("etag", "").strip(chr(34))
        if start is not None and "/api/" in r.url:
            spans.append(
                {
                    "url": r.url.split("/api/")[1],
                    "method": r.request.method,
                    "status": r.status,
                    "at_seconds": time.perf_counter() - start,
                }
            )

    def finished(request: Request) -> None:
        if request.url.endswith(f"/templates/{name}/preparation"):
            result = request.response()
            if result and result.status == 200:
                preparation_responses.append(result.json())

    page.on("response", response)
    page.on("requestfinished", finished)
    print(f"Editing {name} {kind} {repeat}", flush=True)
    if kind == "mask":
        page.get_by_role("button", name="Edit mask", exact=True).click()
        page.get_by_label("Mask drawing area").wait_for()
        area = page.locator(".quad-editor__polygon").first.bounding_box()
        assert area
        fraction = (
            (0.35 + repeat * 0.06)
            if page.locator(".quad-editor__polygon").count() == 1
            else (0.07 + repeat * 0.035)
        )
        x = area["x"] + area["width"] * fraction
        y = area["y"] + area["height"] * 0.45
        point = {"x": x, "y": y}
        if interactive:
            before_pixel = page.get_by_alt_text("Rendered preview").first.evaluate(PIXEL_JS, point)
        page.mouse.move(x, y)
        clip = {"x": x - 8, "y": y - 8, "width": 24, "height": 24}
        before_stroke = page.screenshot(clip=clip)
        feedback_start = time.perf_counter()
        page.mouse.down()
        after_stroke = page.screenshot(clip=clip)
        feedback = time.perf_counter() - feedback_start
        assert not np.array_equal(
            np.asarray(Image.open(BytesIO(before_stroke))),
            np.asarray(Image.open(BytesIO(after_stroke))),
        ), "Stroke must change visible pixels"
        page.mouse.move(x + 5, y + 5, steps=2)
        start = time.perf_counter()
        page.mouse.up()
        page.get_by_role("button", name="Done", exact=True).click()
    else:
        # Moving one corner inward keeps the full conservative crop covered.
        corner = page.locator(".quad-editor__handle").first
        corner.scroll_into_view_if_needed()
        if not corner.count():
            corner = page.locator("[data-corner]").first
        bounds = corner.bounding_box()
        assert bounds, "Find observable corner handle"
        page.mouse.move(
            bounds["x"] + bounds["width"] / 2,
            bounds["y"] + bounds["height"] / 2,
        )
        page.mouse.down()
        page.wait_for_timeout(50)
        page.mouse.move(
            bounds["x"] + bounds["width"] / 2 + 2,
            bounds["y"] + bounds["height"] / 2 + 2,
            steps=5,
        )
        start = time.perf_counter()
        page.mouse.up()
    if interactive:
        image = page.get_by_alt_text("Rendered preview").first
        seen_source = old_editor_source
        deadline = time.monotonic() + 180
        while True:
            page.wait_for_function(
                """old => {
                    const i=document.querySelector('.quad-editor img');
                    return i && i.src.startsWith('blob:') && i.src !== old;
                }""",
                arg=seen_source,
            )
            decoded = image.evaluate(DECODE_JS)
            end = time.perf_counter()
            fingerprint = image.evaluate(FINGERPRINT_JS)
            if fingerprint != old_fingerprint:
                break
            # Autosave acknowledgement can legitimately refresh the same pixels.
            # It is not evidence that the new edit has reached the composite.
            seen_source = image.get_attribute("src")
            if time.monotonic() > deadline:
                raise TimeoutError("No changed composite: " + json.dumps(spans))
        after_pixel = image.evaluate(PIXEL_JS, point) if point else None
        if before_pixel is not None:
            assert sum(abs(a - b) for a, b in zip(before_pixel, after_pixel, strict=True)) > 30, (
                "Mask must change the decoded artwork pixel: " + str((before_pixel, after_pixel))
            )

        displayed_preparation = page.evaluate(
            "async name => (await fetch('/api/templates/' + encodeURIComponent(name) + "
            "'/preparation')).json()",
            name,
        )
        active_before = initial_preparation["active_job"]
        active_after = displayed_preparation["active_job"]
        row = {
            "template": name,
            "edit": kind,
            "repeat": repeat,
            "cache": "warm" if interactive else ("first" if repeat == 0 else "warm"),
            "service_seconds": end - start,
            "edit_to_display_seconds": end - start,
            "stroke_feedback_upper_bound_seconds": feedback,
            "fingerprint": fingerprint,
            "before_fingerprint": old_fingerprint,
            "rebuild_active_at_edit": bool(active_before),
            "same_rebuild_active_through_display": bool(
                active_before and active_after and active_before["id"] == active_after["id"]
            ),
            "before_pixel": before_pixel,
            "after_pixel": after_pixel,
            **decoded,
            "responses": list(spans),
        }
        print(json.dumps(row), flush=True)
        # The default isolates steady-state service cost. The contention mode
        # starts the next edit as soon as autosave has queued/runs a rebuild.
        deadline = time.monotonic() + 180
        while not saved_revision or not any(
            p["config_revision"] == saved_revision
            and (
                bool(p["active_job"])
                if during_rebuild
                else (p["maps"]["can_render"] and not p["active_job"])
            )
            for p in preparation_responses
        ):
            if time.monotonic() > deadline:
                raise TimeoutError("Background publication did not finish: " + json.dumps(spans))
            page.wait_for_timeout(25)
        page.remove_listener("response", response)
        page.remove_listener("requestfinished", finished)
        return row
    save_deadline = time.monotonic() + 180
    while not saved_revision or not any(
        p["config_revision"] == saved_revision and p["maps"]["can_render"] and not p["active_job"]
        for p in preparation_responses
    ):
        if time.monotonic() > save_deadline:
            page.screenshot(path=str(output / "save-timeout.png"))
            raise TimeoutError("No current ready generation: " + json.dumps(spans))
        page.wait_for_timeout(25)
    page.wait_for_function(
        """() => document.querySelector('.mg-preparation .mg-status')
                        ?.textContent === 'Ready'"""
    )
    ready = time.perf_counter()
    old_source = (
        page.locator(".preview-grid__tile img").first.get_attribute("src")
        if page.locator(".preview-grid__tile img").count()
        else None
    )
    clicked = time.perf_counter()
    with page.expect_response(
        lambda r: "/preview?scale=full" in r.url and r.request.method == "POST" and r.status == 200
    ):
        page.get_by_role("tab", name="Preview", exact=True).click()
        render = page.get_by_role("button", name="Re-render", exact=True)
        if old_source:
            render.click()
    image = page.locator(".preview-grid__tile img").first
    image.wait_for()
    page.wait_for_function(
        """old => {
            const i=document.querySelector('.preview-grid__tile img');
            return i && i.src !== old;
        }""",
        arg=old_source,
    )
    decoded = image.evaluate(DECODE_JS)
    end = time.perf_counter()
    fingerprint = image.evaluate(FINGERPRINT_JS)
    row = {
        "template": name,
        "stroke_feedback_upper_bound_seconds": feedback,
        "edit": kind,
        "repeat": repeat,
        "cache": "warm" if interactive else ("first" if repeat == 0 else "warm"),
        "edit_to_ready_seconds": ready - start,
        "explicit_render_dwell_seconds": clicked - ready,
        "edit_to_display_seconds": end - start,
        "service_seconds": end - start - (clicked - ready),
        "fingerprint": fingerprint,
        **decoded,
        "responses": list(spans),
        "checkpoints": [
            (identity, step, at - start) for identity, step, at in checkpoints if at >= start
        ],
    }
    page.remove_listener("response", response)
    page.remove_listener("requestfinished", finished)
    print(json.dumps(row), flush=True)
    return row


def implementation_fingerprint() -> str:
    """Identify dirty source as well as HEAD when comparing local iterations."""
    names = subprocess.check_output(
        [
            "git",
            "ls-files",
            "-co",
            "--exclude-standard",
            "src/etsy_listings",
            "src/ui/src",
            "scripts",
        ],
        text=True,
    ).splitlines()
    digest = hashlib.sha256()
    for name in sorted(set(names)):
        path = Path(name)
        if path.is_file():
            digest.update(name.encode("utf-8") + bytes([0]))
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def run(
    source: Path,
    output: Path,
    repeats: int,
    threshold: float,
    interactive: bool = False,
    names: list[str] | None = None,
    edits: list[str] | None = None,
    artwork_size: tuple[int, int] = (512, 512),
    during_rebuild: bool = False,
) -> None:
    if output.exists() or output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Output must be a new isolated directory")
    output.mkdir(parents=True)
    root = output / "workspace"
    shutil.copytree(source, root)
    workspace = Workspace.discover(root_override=root)
    workspace.test_designs_dir().mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", artwork_size, (230, 35, 160, 255)).save(
        workspace.test_design_file("benchmark-contrast")
    )
    app = create_app(workspace, preparation_runtime=EvidenceOnlyRuntime())
    checkpoints = []
    app.state.preparations.checkpoint = lambda identity, step: checkpoints.append(
        (identity, step, time.perf_counter())
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 180
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Server failed to start")
        time.sleep(0.05)
    rows = []
    warmups = []
    names = names or ["folded-bay", "multiple-validation"]
    edits = edits or ["mask", "geometry"]
    browser_version = None
    print("Server started", flush=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser_version = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.set_default_timeout(180_000)

            def rejected_preview(response: Response) -> None:
                if "/preview?scale=editor" in response.url and response.status != 200:
                    print("Editor preview refused: " + response.text(), flush=True)

            page.on("response", rejected_preview)
            page.goto(f"http://127.0.0.1:{port}/templates")
            for name in names:
                warmup_start = time.perf_counter()
                print("Selecting " + name, flush=True)
                page.get_by_role("searchbox", name="Search templates").fill(name)
                page.locator(f'.template-rail__item[data-template="{name}"]').click()
                page.wait_for_function(
                    """() => document.querySelector('.mg-preparation .mg-status')
                        ?.textContent === 'Ready'"""
                )
                picker = page.get_by_label("Test design", exact=True)
                old_design = picker.input_value()
                old_src = page.get_by_alt_text("Rendered preview").first.get_attribute("src")
                picker.select_option("benchmark-contrast")
                if interactive:
                    page.wait_for_function(
                        """old => {
                        const i=document.querySelector('.quad-editor img');
                        return i && i.src.startsWith('blob:') && i.complete &&
                            (old === null || i.src !== old);
                    }""",
                        arg=old_src if old_design != "benchmark-contrast" else None,
                        timeout=60_000,
                    )
                    page.get_by_alt_text("Rendered preview").first.evaluate(DECODE_JS)
                    warmups.append(
                        {
                            "template": name,
                            "initial_image_seconds": time.perf_counter() - warmup_start,
                        }
                    )
                for kind in edits:
                    for repeat in range(repeats):
                        row = measure(
                            page,
                            name,
                            kind,
                            repeat,
                            output,
                            checkpoints,
                            interactive,
                            during_rebuild,
                        )
                        rows.append(row)
                        (output / "raw-rows.json").write_text(
                            json.dumps(rows, indent=2), encoding="utf-8"
                        )
            browser.close()
    finally:
        server.should_exit = True
        thread.join(180)
        report = {
            "machine": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pillow": pillow_version,
            "browser": browser_version,
            "cpu": platform.processor(),
            "logical_processors": os.cpu_count(),
            "thread_environment": {
                k: os.environ.get(k)
                for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]
            },
            "implementation_fingerprint": implementation_fingerprint(),
            "git_tip": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "source": str(source.resolve()),
            "mode": "interactive" if interactive else "full",
            "artwork_size": artwork_size,
            "during_rebuild": during_rebuild,
            "warmups": warmups,
            "summary": {
                name + "/" + kind: {
                    "median_seconds": statistics.median(
                        [
                            r["service_seconds"]
                            for r in rows
                            if r["template"] == name and r["edit"] == kind
                        ]
                    ),
                    "max_seconds": max(
                        r["service_seconds"]
                        for r in rows
                        if r["template"] == name and r["edit"] == kind
                    ),
                }
                for name in names
                for kind in edits
                if any(r["template"] == name and r["edit"] == kind for r in rows)
            },
            "opencv": cv2.__version__,
            "opencv_threads": cv2.getNumThreads(),
            "threshold_seconds": threshold,
            "rows": rows,
        }
        (output / "measurements.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    assert len(rows) == repeats * len(names) * len(edits)
    if during_rebuild:
        for name in names:
            for kind in edits:
                assert any(
                    row["rebuild_active_at_edit"]
                    for row in rows
                    if row["template"] == name and row["edit"] == kind
                ), "Contention mode did not overlap a rebuild for " + name + "/" + kind
    warm = [r for r in rows if r["cache"] == "warm"]
    measured = warm if warm else rows
    assert max(r["service_seconds"] for r in measured) < threshold, (
        "Edit-to-display target exceeded"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--during-rebuild", action="store_true")
    parser.add_argument("--template", action="append")
    parser.add_argument("--artwork-size", nargs=2, type=int, default=(512, 512))
    parser.add_argument("--edit", action="append", choices=["mask", "geometry"])
    args = parser.parse_args()
    run(
        args.source,
        args.output,
        args.repeats,
        args.threshold,
        args.interactive,
        args.template,
        args.edit,
        tuple(args.artwork_size),
        args.during_rebuild,
    )

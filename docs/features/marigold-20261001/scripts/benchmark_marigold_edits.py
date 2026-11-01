"""Measure real edit-to-decoded-preview latency in an isolated prepared workspace.

No model inference is permitted. The source is copied, never opened for writing.
Use a new output directory for each comparison. Prepared real photos remain external.
"""

from __future__ import annotations

import argparse
import base64
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
from dataclasses import dataclass, field
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from typing import Any, override

import cv2
import numpy as np
import uvicorn
from PIL import Image
from PIL import __version__ as pillow_version
from playwright.sync_api import Page, Request, Response, sync_playwright

from etsy_listings.core.application.preparation.dependencies import PreparationRuntime
from etsy_listings.core.preparation.runtime import Capability
from etsy_listings.core.workspace import Workspace
from etsy_listings.server.api import app as api_app
from etsy_listings.server.api.app import create_app

# The smallest per-channel difference that counts as ink, or as a changed pixel.
VISIBLE_INK = 30

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


PNG_JS = """img => {
  const c=document.createElement('canvas');
  c.width=img.naturalWidth; c.height=img.naturalHeight;
  c.getContext('2d').drawImage(img, 0, 0);
  return c.toDataURL('image/png').split(',')[1];
}"""


def visible_ink_point(
    page: Page, area: dict[str, float], background: Image.Image
) -> dict[str, float]:
    """Choose actual visible print ink, including designs with transparent margins."""
    image = page.get_by_alt_text("Rendered preview").first
    bounds = image.bounding_box()
    assert bounds
    actual = np.asarray(
        Image.open(BytesIO(base64.b64decode(image.evaluate(PNG_JS)))).convert("RGB")
    )
    height, width = actual.shape[:2]
    reference = cv2.resize(np.asarray(background), (width, height), interpolation=cv2.INTER_AREA)
    difference = np.abs(actual.astype(np.int16) - reference.astype(np.int16)).sum(axis=2)
    # Stay inside the first placement's bounds. Pixels that differ strongly
    # from the original photo locate ink without assuming an artwork silhouette.
    x0 = max(0, round((area["x"] + area["width"] * 0.08 - bounds["x"]) / bounds["width"] * width))
    x1 = min(
        width, round((area["x"] + area["width"] * 0.92 - bounds["x"]) / bounds["width"] * width)
    )
    y0 = max(
        0, round((area["y"] + area["height"] * 0.08 - bounds["y"]) / bounds["height"] * height)
    )
    y1 = min(
        height, round((area["y"] + area["height"] * 0.92 - bounds["y"]) / bounds["height"] * height)
    )
    region = difference[y0:y1, x0:x1]
    assert region.size, "Real artwork must have visible ink to mask"
    assert region.max() > VISIBLE_INK, "Real artwork must have visible ink to mask"
    y, x = np.unravel_index(region.argmax(), region.shape)
    return {
        "x": bounds["x"] + (x0 + int(x) + 0.5) * bounds["width"] / width,
        "y": bounds["y"] + (y0 + int(y) + 0.5) * bounds["height"] / height,
    }


class EvidenceOnlyRuntime(PreparationRuntime):
    @override
    def inspect(self) -> Capability:
        return Capability(available=False, problem="Benchmark forbids model inference")

    @override
    def selection(self, version: str, *, installation_id: str | None = None) -> Capability:
        raise AssertionError("Benchmark must not select a model")

    @override
    def worker(self, selected: Capability, *, cache_root: Path) -> Any:
        raise AssertionError("Benchmark must never run model inference")


@dataclass(frozen=True)
class BenchmarkOptions:
    """The command line: how many repeats, the pass threshold, and what to
    edit, render and serve."""

    repeats: int = 4
    threshold: float = 1
    interactive: bool = False
    names: list[str] | None = None
    edits: list[str] | None = None
    artwork_size: tuple[int, int] = (512, 512)
    during_rebuild: bool = False
    frontend_dist: Path | None = None
    design: str | None = None


@dataclass(frozen=True)
class Trial:
    """One measurement: an edit ``kind`` on template ``name``, repeat ``repeat``."""

    name: str
    kind: str
    repeat: int


@dataclass(frozen=True)
class _Session:
    """What every measurement of one run shares."""

    output: Path
    checkpoints: list[tuple[str, str, float]]
    options: BenchmarkOptions


PREPARATION_JS = (
    "async name => (await fetch('/api/templates/' + encodeURIComponent(name) + "
    "'/preparation')).json()"
)
READY_JS = """() => document.querySelector('.mg-preparation .mg-status')
                        ?.textContent === 'Ready'"""
PUBLICATION_TIMEOUT_S = 180


class _Measurement:
    """One trial: make the edit, time it until its result is displayed, and
    collect the API responses and preparation states seen on the way."""

    def __init__(
        self, page: Page, trial: Trial, session: _Session, mask_background: Image.Image | None
    ) -> None:
        self.page = page
        self.trial = trial
        self.session = session
        self.mask_background = mask_background
        self.interactive = session.options.interactive
        self.spans: list[dict[str, Any]] = []
        self.start: float | None = None
        self.feedback: float | None = None
        self.preparation_responses: list[dict[str, Any]] = []
        self.saved_revision: str | None = None
        self.point: dict[str, float] | None = None
        self.before_pixel: list[int] | None = None

    def response(self, r: Response) -> None:
        if r.request.method == "PUT" and r.url.endswith("/config"):
            self.saved_revision = r.headers.get("etag", "").strip(chr(34))
        if self.start is not None and "/api/" in r.url:
            self.spans.append(
                {
                    "url": r.url.split("/api/")[1],
                    "method": r.request.method,
                    "status": r.status,
                    "at_seconds": time.perf_counter() - self.start,
                }
            )

    def finished(self, request: Request) -> None:
        if request.url.endswith(f"/templates/{self.trial.name}/preparation"):
            result = request.response()
            if result and result.status == HTTPStatus.OK:
                self.preparation_responses.append(result.json())

    def run(self) -> dict[str, Any]:
        page, trial = self.page, self.trial
        self._open_calibration()
        old_editor_source = page.get_by_alt_text("Rendered preview").first.get_attribute("src")
        old_fingerprint = (
            page.get_by_alt_text("Rendered preview").first.evaluate(FINGERPRINT_JS)
            if self.interactive
            else None
        )
        initial_preparation = self._preparation()
        page.on("response", self.response)
        page.on("requestfinished", self.finished)
        print(f"Editing {trial.name} {trial.kind} {trial.repeat}", flush=True)
        if trial.kind == "mask":
            self._edit_mask()
        else:
            self._edit_geometry()
        if self.interactive:
            return self._interactive(old_editor_source, old_fingerprint, initial_preparation)
        return self._full()

    def _started(self) -> float:
        assert self.start is not None, "every edit starts the clock"
        return self.start

    def _preparation(self) -> dict[str, Any]:
        return self.page.evaluate(PREPARATION_JS, self.trial.name)

    def _stop_listening(self) -> None:
        self.page.remove_listener("response", self.response)
        self.page.remove_listener("requestfinished", self.finished)

    def _open_calibration(self) -> None:
        page = self.page
        page.get_by_role("tab", name="Calibrate", exact=True).click()
        polygon = page.locator(".quad-editor__polygon").first
        bounds = polygon.bounding_box()
        assert bounds
        page.mouse.click(
            bounds["x"] + bounds["width"] * 0.07, bounds["y"] + bounds["height"] * 0.45
        )
        if self.interactive:
            page.wait_for_function(
                """() => {
                    const i=document.querySelector('.quad-editor img');
                    return i && i.src.startsWith('blob:') && i.complete &&
                        i.naturalWidth === 1024 && i.naturalHeight === 1024;
                }"""
            )

    def _mask_point(self, area: dict[str, float]) -> dict[str, float]:
        repeat = self.trial.repeat
        fraction = (
            (0.35 + repeat * 0.06)
            if self.page.locator(".quad-editor__polygon").count() == 1
            else (0.07 + repeat * 0.035)
        )
        if self.mask_background is not None:
            return visible_ink_point(self.page, area, self.mask_background)
        return {"x": area["x"] + area["width"] * fraction, "y": area["y"] + area["height"] * 0.45}

    def _edit_mask(self) -> None:
        page = self.page
        page.get_by_role("button", name="Edit mask", exact=True).click()
        page.get_by_label("Mask drawing area").wait_for()
        area = page.locator(".quad-editor__polygon").first.bounding_box()
        assert area
        self.point = self._mask_point(area)
        x, y = self.point["x"], self.point["y"]
        if self.interactive:
            self.before_pixel = page.get_by_alt_text("Rendered preview").first.evaluate(
                PIXEL_JS, self.point
            )
        page.mouse.move(x, y)
        clip = {"x": x - 8, "y": y - 8, "width": 24, "height": 24}
        before_stroke = page.screenshot(clip=clip)
        feedback_start = time.perf_counter()
        page.mouse.down()
        after_stroke = page.screenshot(clip=clip)
        self.feedback = time.perf_counter() - feedback_start
        assert not np.array_equal(
            np.asarray(Image.open(BytesIO(before_stroke))),
            np.asarray(Image.open(BytesIO(after_stroke))),
        ), "Stroke must change visible pixels"
        page.mouse.move(x + 5, y + 5, steps=2)
        self.start = time.perf_counter()
        page.mouse.up()
        page.get_by_role("button", name="Done", exact=True).click()

    def _edit_geometry(self) -> None:
        page = self.page
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
        self.start = time.perf_counter()
        page.mouse.up()

    def _changed_composite(
        self, image: Any, old_source: str | None, old_fingerprint: str | None
    ) -> tuple[dict[str, Any], float, str]:
        """The first decoded composite whose pixels differ from the old one."""
        seen_source = old_source
        deadline = time.monotonic() + 180
        while True:
            self.page.wait_for_function(
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
                return decoded, end, fingerprint
            # Autosave acknowledgement can legitimately refresh the same pixels.
            # It is not evidence that the new edit has reached the composite.
            seen_source = image.get_attribute("src")
            if time.monotonic() > deadline:
                raise TimeoutError("No changed composite: " + json.dumps(self.spans))

    def _interactive(
        self,
        old_editor_source: str | None,
        old_fingerprint: str | None,
        initial_preparation: dict[str, Any],
    ) -> dict[str, Any]:
        trial = self.trial
        image = self.page.get_by_alt_text("Rendered preview").first
        decoded, end, fingerprint = self._changed_composite(
            image, old_editor_source, old_fingerprint
        )
        assert decoded == {"width": 1024, "height": 1024}, (
            "Interactive benchmark requires an actual decoded 1024px square composite"
        )
        after_pixel = image.evaluate(PIXEL_JS, self.point) if self.point else None
        if self.before_pixel is not None:
            assert (
                sum(abs(a - b) for a, b in zip(self.before_pixel, after_pixel, strict=True))
                > VISIBLE_INK
            ), "Mask must change the decoded artwork pixel: " + str(
                (self.before_pixel, after_pixel)
            )
        row = self._interactive_row(
            _Timing(self._started(), end, fingerprint, old_fingerprint),
            (initial_preparation["active_job"], self._preparation()["active_job"]),
            after_pixel,
            decoded,
        )
        # Capture the actual decoded raster after stopping the clock, so review
        # can inspect native detail rather than a CSS-scaled screen capture.
        png = image.evaluate(PNG_JS)
        (self.session.output / f"{trial.name}-{trial.kind}-{trial.repeat}-decoded.png").write_bytes(
            base64.b64decode(png)
        )
        print(json.dumps(row), flush=True)
        self._await_publication()
        self._stop_listening()
        return row

    def _interactive_row(
        self,
        timing: _Timing,
        active: tuple[dict[str, Any] | None, dict[str, Any] | None],
        after_pixel: list[int] | None,
        decoded: dict[str, Any],
    ) -> dict[str, Any]:
        trial = self.trial
        start, end = timing.start, timing.end
        active_before, active_after = active
        return {
            "template": trial.name,
            "edit": trial.kind,
            "repeat": trial.repeat,
            "cache": "warm",
            "service_seconds": end - start,
            "edit_to_display_seconds": end - start,
            "stroke_feedback_upper_bound_seconds": self.feedback,
            "fingerprint": timing.fingerprint,
            "before_fingerprint": timing.before_fingerprint,
            "rebuild_active_at_edit": bool(active_before),
            "rebuild_phase_at_edit": _phase(active_before),
            "rebuild_phase_after_display": _phase(active_after),
            "checkpoints": [
                (identity, step, at - start)
                for identity, step, at in self.session.checkpoints
                if start <= at <= end
            ],
            "same_rebuild_active_through_display": _same_job(active_before, active_after),
            "before_pixel": self.before_pixel,
            "after_pixel": after_pixel,
            "mask_point": self.point,
            "mask_target": "visible-artwork"
            if self.mask_background is not None
            else "fixed-contrast",
            **decoded,
            "responses": list(self.spans),
        }

    def _published(self, preparation: dict[str, Any]) -> bool:
        if preparation["config_revision"] != self.saved_revision:
            return False
        # The default isolates steady-state service cost. The contention mode
        # starts the next edit as soon as autosave has queued/runs a rebuild.
        if self.session.options.during_rebuild:
            return bool(preparation["active_job"])
        return bool(_ready(preparation))

    def _await_publication(self) -> None:
        deadline = time.monotonic() + PUBLICATION_TIMEOUT_S
        while not self.saved_revision or not any(
            self._published(p) for p in self.preparation_responses
        ):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Background publication did not finish: " + json.dumps(self.spans)
                )
            self.page.wait_for_timeout(25)

    def _await_ready_generation(self) -> None:
        save_deadline = time.monotonic() + PUBLICATION_TIMEOUT_S
        while not self.saved_revision or not any(
            p["config_revision"] == self.saved_revision and _ready(p)
            for p in self.preparation_responses
        ):
            if time.monotonic() > save_deadline:
                self.page.screenshot(path=str(self.session.output / "save-timeout.png"))
                raise TimeoutError("No current ready generation: " + json.dumps(self.spans))
            self.page.wait_for_timeout(25)

    def _full(self) -> dict[str, Any]:
        page, trial = self.page, self.trial
        self._await_ready_generation()
        page.wait_for_function(READY_JS)
        ready = time.perf_counter()
        old_source = (
            page.locator(".preview-grid__tile img").first.get_attribute("src")
            if page.locator(".preview-grid__tile img").count()
            else None
        )
        clicked = time.perf_counter()
        with page.expect_response(_full_preview_response):
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
        start = self._started()
        row = {
            "template": trial.name,
            "stroke_feedback_upper_bound_seconds": self.feedback,
            "edit": trial.kind,
            "repeat": trial.repeat,
            "cache": "first" if trial.repeat == 0 else "warm",
            "edit_to_ready_seconds": ready - start,
            "explicit_render_dwell_seconds": clicked - ready,
            "edit_to_display_seconds": end - start,
            "service_seconds": end - start - (clicked - ready),
            "fingerprint": fingerprint,
            **decoded,
            "responses": list(self.spans),
            "checkpoints": [
                (identity, step, at - start)
                for identity, step, at in self.session.checkpoints
                if at >= start
            ],
        }
        self._stop_listening()
        print(json.dumps(row), flush=True)
        return row


@dataclass(frozen=True)
class _Timing:
    start: float
    end: float
    fingerprint: str
    before_fingerprint: str | None


def _phase(job: dict[str, Any] | None) -> str | None:
    return job["phase"] if job else None


def _same_job(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    return bool(before and after and before["id"] == after["id"])


def _ready(preparation: dict[str, Any]) -> bool:
    return preparation["maps"]["can_render"] and not preparation["active_job"]


def _full_preview_response(r: Response) -> bool:
    return (
        "/preview?scale=full" in r.url and r.request.method == "POST" and r.status == HTTPStatus.OK
    )


def measure(
    page: Page,
    trial: Trial,
    session: _Session,
    *,
    mask_background: Image.Image | None = None,
) -> dict[str, Any]:
    return _Measurement(page, trial, session, mask_background).run()


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
            "docs/features/marigold-20261001/scripts",
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


def _isolated_workspace(source: Path, output: Path, artwork_size: tuple[int, int]) -> Workspace:
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
    return workspace


@dataclass
class _Server:
    server: uvicorn.Server
    thread: threading.Thread
    port: int

    @classmethod
    def start(cls, app: Any) -> _Server:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 180
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Server failed to start")
            time.sleep(0.05)
        return cls(server, thread, port)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(180)


@dataclass
class _Results:
    """What a run has measured so far; reported even when it fails."""

    names: list[str]
    edits: list[str]
    rows: list[dict[str, Any]] = field(default_factory=list)
    warmups: list[dict[str, Any]] = field(default_factory=list)
    browser_version: str | None = None


def _rejected_preview(response: Response) -> None:
    if "/preview?scale=editor" in response.url and response.status != HTTPStatus.OK:
        print("Editor preview refused: " + response.text(), flush=True)


def _select_template(page: Page, name: str, options: BenchmarkOptions, results: _Results) -> None:
    warmup_start = time.perf_counter()
    print("Selecting " + name, flush=True)
    page.get_by_role("searchbox", name="Search templates").fill(name)
    page.locator(f'.template-rail__item[data-template="{name}"]').click()
    page.wait_for_function(READY_JS)
    design = options.design or "benchmark-contrast"
    picker = page.get_by_label("Test design", exact=True)
    old_design = picker.input_value()
    old_src = page.get_by_alt_text("Rendered preview").first.get_attribute("src")
    picker.select_option(design)
    if not options.interactive:
        return
    page.wait_for_function(
        """old => {
        const i=document.querySelector('.quad-editor img');
        return i && i.src.startsWith('blob:') && i.complete &&
            (old === null || i.src !== old);
    }""",
        arg=old_src if old_design != design else None,
        timeout=60_000,
    )
    page.get_by_alt_text("Rendered preview").first.evaluate(DECODE_JS)
    results.warmups.append(
        {"template": name, "initial_image_seconds": time.perf_counter() - warmup_start}
    )


def _mask_background(workspace: Workspace, name: str, design: str | None) -> Image.Image | None:
    if design is None:
        return None
    with Image.open(workspace.template_main_photo(name)) as photo:
        return photo.convert("RGB")


def _drive_browser(port: int, workspace: Workspace, session: _Session, results: _Results) -> None:
    options = session.options
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        results.browser_version = browser.version
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.set_default_timeout(180_000)
        page.on("response", _rejected_preview)
        page.goto(f"http://127.0.0.1:{port}/templates")
        for name in results.names:
            _select_template(page, name, options, results)
            mask_background = _mask_background(workspace, name, options.design)
            for kind in results.edits:
                for repeat in range(options.repeats):
                    row = measure(
                        page,
                        Trial(name, kind, repeat),
                        _Session(session.output, session.checkpoints, options),
                        mask_background=mask_background,
                    )
                    results.rows.append(row)
                    (session.output / "raw-rows.json").write_text(
                        json.dumps(results.rows, indent=2), encoding="utf-8"
                    )
        browser.close()


def _rows_for(results: _Results, name: str, kind: str) -> list[dict[str, Any]]:
    return [r for r in results.rows if r["template"] == name and r["edit"] == kind]


def _cases(results: _Results) -> list[tuple[str, str]]:
    return [(name, kind) for name in results.names for kind in results.edits]


def _summary(results: _Results) -> dict[str, dict[str, float]]:
    summary = {}
    for name, kind in _cases(results):
        seconds = [r["service_seconds"] for r in _rows_for(results, name, kind)]
        if seconds:
            summary[name + "/" + kind] = {
                "median_seconds": statistics.median(seconds),
                "max_seconds": max(seconds),
            }
    return summary


def _report(source: Path, options: BenchmarkOptions, results: _Results) -> dict[str, Any]:
    return {
        "machine": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": pillow_version,
        "browser": results.browser_version,
        "cpu": platform.processor(),
        "logical_processors": os.cpu_count(),
        "thread_environment": {
            k: os.environ.get(k)
            for k in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]
        },
        "implementation_fingerprint": implementation_fingerprint(),
        "git_tip": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source": str(source.resolve()),
        "mode": "interactive" if options.interactive else "full",
        "artwork_size": options.artwork_size,
        "design": options.design or "benchmark-contrast",
        "frontend_dist": str(options.frontend_dist) if options.frontend_dist else None,
        "during_rebuild": options.during_rebuild,
        "warmups": results.warmups,
        "summary": _summary(results),
        "opencv": cv2.__version__,
        "opencv_threads": cv2.getNumThreads(),
        "threshold_seconds": options.threshold,
        "rows": results.rows,
    }


def _check(options: BenchmarkOptions, results: _Results) -> None:
    rows = results.rows
    assert len(rows) == options.repeats * len(results.names) * len(results.edits)
    if options.during_rebuild:
        for name, kind in _cases(results):
            assert any(row["rebuild_active_at_edit"] for row in _rows_for(results, name, kind)), (
                "Contention mode did not overlap a rebuild for " + name + "/" + kind
            )
    warm = [r for r in rows if r["cache"] == "warm"]
    measured = warm or rows
    assert max(r["service_seconds"] for r in measured) < options.threshold, (
        "Edit-to-display target exceeded"
    )


def run(source: Path, output: Path, options: BenchmarkOptions) -> None:
    workspace = _isolated_workspace(source, output, options.artwork_size)
    if options.frontend_dist is not None:
        api_app.FRONTEND_DIST = options.frontend_dist.resolve()
    app = create_app(workspace, preparation_runtime=EvidenceOnlyRuntime())
    checkpoints: list[tuple[str, str, float]] = []
    app.state.preparations.checkpoint = lambda identity, step: checkpoints.append(
        (identity, step, time.perf_counter())
    )
    server = _Server.start(app)
    results = _Results(
        names=options.names or ["folded-bay", "multiple-validation"],
        edits=options.edits or ["mask", "geometry"],
    )
    print("Server started", flush=True)
    try:
        _drive_browser(server.port, workspace, _Session(output, checkpoints, options), results)
    finally:
        server.stop()
        (output / "measurements.json").write_text(
            json.dumps(_report(source, options, results), indent=2) + "\n", encoding="utf-8"
        )
    _check(options, results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--during-rebuild", action="store_true")
    parser.add_argument("--frontend-dist", type=Path)
    parser.add_argument("--design", help="Existing test artwork ID, including real source artwork")
    parser.add_argument("--template", action="append")
    parser.add_argument("--artwork-size", nargs=2, type=int, default=(512, 512))
    parser.add_argument("--edit", action="append", choices=["mask", "geometry"])
    args = parser.parse_args()
    run(
        args.source,
        args.output,
        BenchmarkOptions(
            repeats=args.repeats,
            threshold=args.threshold,
            interactive=args.interactive,
            names=args.template,
            edits=args.edit,
            artwork_size=tuple(args.artwork_size),
            during_rebuild=args.during_rebuild,
            frontend_dist=args.frontend_dist,
            design=args.design,
        ),
    )

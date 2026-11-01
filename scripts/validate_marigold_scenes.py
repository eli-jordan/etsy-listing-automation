"""Native colour-matrix and foreground-edge review on external copied inputs.

The folded placement is deliberately shifted 300 photo pixels upward so ink
crosses the chain/pendant. Automatic masks remain unapproved; renders expose
failure instead of correcting it silently. Fence colour sharing uses the original
calibration. Each unsuitable colour already has its own independently prepared
single template. No production per-colour override is invented.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from etsy_listings.core.application.preparation.coordinator import PreparationRequest, Preparations
from etsy_listings.core.application.preparation.models import TERMINAL
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.render import MaterialLayer, render_marigold_scene
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore

# How long normals inference runs before the script interrupts it.
INFERENCE_RUNNING_S = 8
NAMES = ["folded-edge", "folded-edge-ivory", "folded-edge-black", "fence-colours"]
COLOURS = ["bay", "ivory", "black"]


def _write_template(workspace: Workspace, name: str) -> None:
    templates = workspace.root / "mockup-templates"
    reference = "fence-bay" if name == "fence-colours" else "folded-bay"
    original = yaml.safe_load((templates / reference / "template.yaml").read_text(encoding="utf-8"))
    config = dict(original)
    directory = templates / name
    directory.mkdir()
    if name in ("fence-colours", "folded-edge"):
        config["kind"] = "colour-matrix"
        pack = "fence-" if name == "fence-colours" else "folded-"
        for colour in COLOURS:
            shutil.copyfile(
                templates / (pack + colour) / "scene.png", directory / (colour + ".png")
            )
    else:
        colour = name.rsplit("-", 1)[1]
        shutil.copyfile(templates / ("folded-" + colour) / "scene.png", directory / "scene.png")
    if name.startswith("folded-edge"):
        config["bounding_box"] = [{"x": p["x"], "y": p["y"] - 300} for p in config["bounding_box"]]
    (directory / "template.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_report(output: Path, report: dict) -> None:
    (output / "scenes.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


class _Preparer:
    """Prepares each scene in turn. While `fence-colours` infers normals, it
    closes the coordinator once and continues on a new one."""

    def __init__(self, workspace: Workspace, report: dict) -> None:
        self.workspace = workspace
        self.report = report
        self.coordinator = Preparations(workspace)
        self.coordinator.start()
        self._normals_started: float | None = None
        self._closed_active = False

    def prepare(self, name: str, output: Path) -> None:
        started = time.perf_counter()
        job = self.coordinator.submit(
            name,
            PreparationRequest(
                config_revision=CalibrationStore(self.workspace).read(name).revision,
                request_id="native-" + name,
            ),
        )
        deadline = time.monotonic() + 900
        seen = None
        self._normals_started = None
        self._closed_active = False
        while (job := self.coordinator.status(job.id)).phase not in TERMINAL:
            if time.monotonic() > deadline:
                self.coordinator.cancel(job.id)
                raise TimeoutError("Native scene preparation exceeded its deadline")
            if name == "fence-colours" and not self._closed_active:
                self._close_while_inferring(job)
            if seen != job.step:
                print(name, job.step, flush=True)
                seen = job.step
            time.sleep(0.25)
        self.report["cases"].append(
            {
                "name": name,
                "seconds": time.perf_counter() - started,
                "job": job.model_dump(mode="json"),
            }
        )
        _write_report(output, self.report)
        if job.phase != "completed":
            raise RuntimeError(job.error or job.phase)

    def _close_while_inferring(self, job: Any) -> None:
        if job.step == "normals" and self._normals_started is None:
            self._normals_started = time.perf_counter()
        if not (
            self._normals_started
            and time.perf_counter() - self._normals_started > INFERENCE_RUNNING_S
        ):
            return
        before = time.perf_counter()
        self.coordinator.close()
        self.report["active_coordinator_close_seconds"] = time.perf_counter() - before
        self.report["job_after_graceful_close"] = self.coordinator.status(job.id).model_dump(
            mode="json"
        )
        self.coordinator = Preparations(self.workspace)
        self.coordinator.start()
        self._closed_active = True

    def close(self) -> None:
        self.coordinator.close()


def _artwork_cases(source: Path) -> dict:
    spec = importlib.util.spec_from_file_location(
        "validation", Path(__file__).with_name("validate_marigold.py")
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.artwork_cases(source / "designs/coding-x-music-master-of-packets.png")


def _independent_name(name: str, colour: str) -> str:
    if name == "fence-colours":
        return "fence-" + colour
    return "folded-edge" if colour == "bay" else "folded-edge-" + colour


@dataclass
class _Renders:
    """Renders each colour of a colour-matrix template with its shared maps and
    with the maps of the colour's own single template."""

    workspace: Workspace
    artifacts: Artifacts
    designs: dict
    output: Path
    report: dict

    def template(self, name: str) -> None:
        with self.artifacts.acquire(name, self.artifacts.saved_inputs(name)) as shared:
            for colour in COLOURS:
                self._colour(name, colour, shared)

    def _colour(self, name: str, colour: str, shared: Any) -> None:
        independent_name = _independent_name(name, colour)
        with Image.open(
            self.workspace.root / "mockup-templates" / name / (colour + ".png")
        ) as image:
            base = np.array(image.convert("RGB"))
        with self.artifacts.acquire(
            independent_name, self.artifacts.saved_inputs(independent_name)
        ) as independent:
            for artwork, pixels in self.designs.items():
                for mode, maps in [
                    ("shared", shared.maps[None]),
                    ("independent", independent.maps[None]),
                ]:
                    self._render(base, (name, colour, artwork, mode), MaterialLayer(pixels, maps))
                print("rendered", name, colour, artwork, flush=True)

    def _render(
        self, base: np.ndarray, case: tuple[str, str, str, str], layer: MaterialLayer
    ) -> None:
        name, colour, artwork, mode = case
        started = time.perf_counter()
        image = render_marigold_scene(base, [layer])
        self.report["render_cases"].append(
            {
                "template": name,
                "colour": colour,
                "artwork": artwork,
                "mode": mode,
                "seconds": time.perf_counter() - started,
            }
        )
        image.save(self.output / "renders" / f"{name}-{colour}-{artwork}-{mode}.png")


def run(source: Path, output: Path) -> None:
    workspace = Workspace.discover(root_override=output / "workspace")
    report: dict = {"cases": [], "render_cases": []}
    for name in NAMES:
        _write_template(workspace, name)
    preparer = _Preparer(workspace, report)
    try:
        for name in NAMES:
            preparer.prepare(name, output)
    finally:
        preparer.close()
    renders = _Renders(workspace, Artifacts(workspace), _artwork_cases(source), output, report)
    for name in ["folded-edge", "fence-colours"]:
        renders.template(name)
    _write_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)

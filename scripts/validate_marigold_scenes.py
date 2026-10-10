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
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import TERMINAL
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.render import MaterialLayer, render_marigold_scene
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


def run(source: Path, output: Path) -> None:
    workspace = Workspace.discover(root_override=output / "workspace")
    report: dict = {"cases": [], "render_cases": []}
    names = ["folded-edge", "folded-edge-ivory", "folded-edge-black", "fence-colours"]
    for name in names:
        reference = "fence-bay" if name == "fence-colours" else "folded-bay"
        original = yaml.safe_load(
            (workspace.root / "mockup-templates" / reference / "template.yaml").read_text(
                encoding="utf-8"
            )
        )
        config = dict(original)
        directory = workspace.root / "mockup-templates" / name
        directory.mkdir()
        if name == "fence-colours" or name == "folded-edge":
            config["kind"] = "colour-matrix"
            for colour in ["bay", "ivory", "black"]:
                pack = "fence-" if name == "fence-colours" else "folded-"
                src = workspace.root / "mockup-templates" / (pack + colour) / "scene.png"
                shutil.copyfile(src, directory / (colour + ".png"))
        else:
            colour = name.rsplit("-", 1)[1]
            shutil.copyfile(
                workspace.root / "mockup-templates" / ("folded-" + colour) / "scene.png",
                directory / "scene.png",
            )
        if name.startswith("folded-edge"):
            config["bounding_box"] = [
                {"x": p["x"], "y": p["y"] - 300} for p in config["bounding_box"]
            ]
        (directory / "template.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    coordinator = Preparations(workspace)
    coordinator.start()
    try:
        for name in names:
            started = time.perf_counter()
            job = coordinator.submit(
                name,
                config_revision=CalibrationStore(workspace).read(name).revision,
                request_id="native-" + name,
            )
            deadline = time.monotonic() + 900
            seen = None
            normals_started = None
            closed_active = False
            while (job := coordinator.status(job.id)).phase not in TERMINAL:
                if time.monotonic() > deadline:
                    coordinator.cancel(job.id)
                    raise TimeoutError("Native scene preparation exceeded its deadline")
                if name == "fence-colours" and not closed_active:
                    if job.step == "normals" and normals_started is None:
                        normals_started = time.perf_counter()
                    if normals_started and time.perf_counter() - normals_started > 8:
                        before = time.perf_counter()
                        coordinator.close()
                        report["active_coordinator_close_seconds"] = time.perf_counter() - before
                        report["job_after_graceful_close"] = coordinator.status(job.id).model_dump(
                            mode="json"
                        )
                        coordinator = Preparations(workspace)
                        coordinator.start()
                        closed_active = True
                if seen != job.step:
                    print(name, job.step, flush=True)
                    seen = job.step
                time.sleep(0.25)
            report["cases"].append(
                {
                    "name": name,
                    "seconds": time.perf_counter() - started,
                    "job": job.model_dump(mode="json"),
                }
            )
            (output / "scenes.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            if job.phase != "completed":
                raise RuntimeError(job.error or job.phase)
    finally:
        coordinator.close()
    spec = importlib.util.spec_from_file_location(
        "validation", Path(__file__).with_name("validate_marigold.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    designs = module.artwork_cases(source / "designs/coding-x-music-master-of-packets.png")
    artifacts = Artifacts(workspace)
    for name in ["folded-edge", "fence-colours"]:
        with artifacts.acquire(name, artifacts.saved_inputs(name)) as shared:
            for colour in ["bay", "ivory", "black"]:
                independent_name = (
                    "fence-" + colour
                    if name == "fence-colours"
                    else ("folded-edge" if colour == "bay" else "folded-edge-" + colour)
                )
                with Image.open(
                    workspace.root / "mockup-templates" / name / (colour + ".png")
                ) as image:
                    base = np.array(image.convert("RGB"))
                with artifacts.acquire(
                    independent_name, artifacts.saved_inputs(independent_name)
                ) as independent:
                    for artwork, pixels in designs.items():
                        for mode, maps in [
                            ("shared", shared.maps[None]),
                            ("independent", independent.maps[None]),
                        ]:
                            started = time.perf_counter()
                            image = render_marigold_scene(base, [MaterialLayer(pixels, maps)])
                            report["render_cases"].append(
                                {
                                    "template": name,
                                    "colour": colour,
                                    "artwork": artwork,
                                    "mode": mode,
                                    "seconds": time.perf_counter() - started,
                                }
                            )
                            image.save(output / "renders" / f"{name}-{colour}-{artwork}-{mode}.png")
                        print("rendered", name, colour, artwork, flush=True)
    (output / "scenes.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)

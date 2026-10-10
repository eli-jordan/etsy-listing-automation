"""Repeat native release measurements on copied photos; outputs stay outside Git.

Run with uv run python scripts/validate_marigold.py SOURCE OUTPUT. SOURCE is a
read-only user workspace. OUTPUT must be a new external directory. Production
Runtime, coordinator, artifact reader and renderer are the validation targets.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import TERMINAL
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.render import MaterialLayer, render_marigold_scene
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


def artwork_cases(real: Path) -> dict[str, np.ndarray]:
    """White, saturated colour, fine print and transparent edges challenge ink."""
    result = {}
    for name, colour in [("white", "white"), ("saturated", "magenta")]:
        result[name] = np.array(Image.new("RGBA", (512, 512), colour))
    fine = Image.new("RGBA", (512, 512))
    draw = ImageDraw.Draw(fine)
    for y in range(16, 500, 24):
        draw.text((16, y), "FINE PRINT 0123456789", fill="white", stroke_width=0)
        draw.line((16, y + 14, 496, y + 14), fill="cyan", width=1)
    result["fine"] = np.array(fine)
    alpha = Image.new("RGBA", (512, 512))
    draw = ImageDraw.Draw(alpha)
    draw.ellipse((32, 32, 480, 480), fill=(255, 128, 0, 128))
    draw.rectangle((128, 128, 384, 384), fill=(0, 255, 255, 220))
    result["transparent"] = np.array(alpha)
    with Image.open(real) as image:
        result["real"] = np.array(image.convert("RGBA"))
    return result


def save_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run(source: Path, output: Path) -> None:
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("Output must be outside the read-only source workspace")
    if output.exists() or output.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Output must be a new external directory")
    output.mkdir(parents=True)
    root = output / "workspace"
    root.mkdir()
    (root / "shop.yaml").write_text("etsy: {currency: USD}\n", encoding="utf-8")
    (root / "mockup-templates").mkdir()
    workspace = Workspace.discover(root_override=root)
    report: dict = {"target": "production", "source_read_only": str(source), "cases": []}
    report_path = output / "measurements.json"
    packs = ["cc-1717-folded-with-hat-and-leaf", "cc1717-hanging-on-fence"]
    for pack in packs:
        original = source / "mockup-templates" / pack
        old = yaml.safe_load((original / "template.yaml").read_text(encoding="utf-8"))
        for colour in ["bay", "ivory", "black"]:
            name = ("folded" if pack == packs[0] else "fence") + "-" + colour
            directory = root / "mockup-templates" / name
            directory.mkdir()
            photo = next(original.glob("*-" + colour + ".png"))
            shutil.copyfile(photo, directory / "scene.png")
            config = {
                "kind": "single",
                "bounding_box": old["bounding_box"],
                "renderer": {"type": "marigold", "config": {}},
            }
            (directory / "template.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    runtime = Runtime()
    started = time.perf_counter()
    capability = runtime.inspect()
    report["runtime_inspect_seconds"] = time.perf_counter() - started
    report["runtime"] = capability.__dict__
    save_report(report_path, report)
    if not capability.available:
        raise RuntimeError(capability.problem)
    coordinator = Preparations(workspace, runtime=runtime)
    coordinator.start()
    try:
        for name in [
            "folded-bay",
            "folded-ivory",
            "folded-black",
            "fence-bay",
            "fence-ivory",
            "fence-black",
        ]:
            started = time.perf_counter()
            record = coordinator.submit(
                name,
                config_revision=CalibrationStore(workspace).read(name).revision,
                request_id="validation-" + name,
            )
            deadline = time.monotonic() + 900
            seen = None
            while (job := coordinator.status(record.id)).phase not in TERMINAL:
                if time.monotonic() > deadline:
                    coordinator.cancel(job.id)
                    raise TimeoutError("Coordinator measurement exceeded 900 seconds")
                if job.step != seen:
                    print(
                        name,
                        job.phase,
                        job.step,
                        round(time.perf_counter() - started, 3),
                        flush=True,
                    )
                    seen = job.step
                time.sleep(0.25)
            case = {
                "name": name,
                "seconds": time.perf_counter() - started,
                "job": job.model_dump(mode="json"),
            }
            report["cases"].append(case)
            save_report(report_path, report)
            if job.phase != "completed":
                print("FAILED", name, job.error, flush=True)
    finally:
        started = time.perf_counter()
        coordinator.close()
        report["idle_coordinator_close_seconds"] = time.perf_counter() - started
        save_report(report_path, report)
    designs = artwork_cases(source / "designs" / "coding-x-music-master-of-packets.png")
    renders = output / "renders"
    renders.mkdir()
    report["render_cases"] = []
    for pack in ["folded", "fence"]:
        reference = pack + "-bay"
        with Artifacts(workspace).acquire(
            reference, Artifacts(workspace).saved_inputs(reference)
        ) as shared:
            for colour in ["bay", "ivory", "black"]:
                name = pack + "-" + colour
                with Image.open(root / "mockup-templates" / name / "scene.png") as image:
                    base = np.array(image.convert("RGB"))
                with Artifacts(workspace).acquire(
                    name, Artifacts(workspace).saved_inputs(name)
                ) as independent:
                    for artwork, pixels in designs.items():
                        for mode, maps in [
                            ("shared", shared.maps[None]),
                            ("independent", independent.maps[None]),
                        ]:
                            started = time.perf_counter()
                            image = render_marigold_scene(base, [MaterialLayer(pixels, maps)])
                            elapsed = time.perf_counter() - started
                            path = renders / (name + "-" + artwork + "-" + mode + ".png")
                            encoded = time.perf_counter()
                            image.save(path)
                            report["render_cases"].append(
                                {
                                    "name": name,
                                    "artwork": artwork,
                                    "mode": mode,
                                    "render_seconds": elapsed,
                                    "encode_seconds": time.perf_counter() - encoded,
                                }
                            )
                        print("rendered", name, artwork, flush=True)
                        save_report(report_path, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.source, args.output)

"""Create an external 2048px latency fixture using fixed numeric predictions.

No photographs, model weights, remote credentials or network calls are used.
The worker seam supplies deterministic normals/lighting/depth; coordinator,
mask persistence, evidence validation, fitting and publication remain real.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import TERMINAL
from etsy_listings.core.preparation.distribution.src.marigold_worker.protocol import (
    InferenceResult,
    Progress,
    Role,
)
from etsy_listings.core.preparation.runtime import Capability
from etsy_listings.core.render import load_template_config
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


class FixedWorker:
    def __init__(self, root: Path) -> None:
        self.root = root

    def infer(
        self,
        *,
        request_id: str,
        role: Role,
        input: str,
        output: str,
        size: tuple[int, int],
        num_inference_steps: int = 10,
        ensemble_size: int = 3,
        progress: Callable[[Progress], None] | None = None,
        dispatch_guard: Callable[[], AbstractContextManager[None]] = nullcontext,
    ) -> InferenceResult:
        with dispatch_guard():
            width, height = size
            yy, xx = np.mgrid[:height, :width].astype(np.float32)
            if role == "normals":
                nx, ny = 0.06 * np.sin(xx / 83), 0.04 * np.cos(yy / 101)
                array = np.stack([nx, ny, np.sqrt(1 - nx**2 - ny**2)], -1)[None]
            elif role == "depth":
                array = (0.5 + 0.02 * np.cos(xx / 83))[None, ..., None]
            else:
                array = np.full((3, height, width, 3), 0.5, np.float32)
                array[2] = 0.005
            path = self.root / output
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(path, prediction=array.astype(np.float32))
            # Only the checksum reaches preparation; the metadata records fixed numerics.
            return InferenceResult.model_validate(
                {
                    "request_id": request_id,
                    "artifact": output,
                    "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "cancelled": False,
                    "metadata": {
                        "engine_version": "1.0.0",
                        "roles": ["normals", "lighting", "depth"],
                        "cuda": False,
                        "gpu": "none",
                        "cuda_version": "none",
                        "model_ram_budget": 0,
                        "resident_models": 0,
                        "installed_packages": {},
                        "packages": {},
                        "checkpoint": "fixed-numeric-fixture",
                        "revision": "fixed",
                        "role": role,
                        "seed": 0,
                        "processing_resolution": max(size),
                        "settings": {
                            "num_inference_steps": num_inference_steps,
                            "ensemble_size": ensemble_size,
                        },
                        "target_properties": {},
                        "normal_frame": "x right, y up, z toward viewer; image rows down",
                        "transforms": {
                            "original_crop_hw": [height, width],
                            "processed_padded_hw": [height, width],
                            "padding": [0, 0, 0, 0],
                            "output_pixel_centres": "integer pixel centres",
                        },
                        "load_seconds": 0.0,
                        "inference_seconds": 0.0,
                        "warm_reuse": True,
                        "resident_model_bytes": 0,
                        "peak_allocated_bytes": 0,
                        "peak_reserved_bytes": 0,
                        "process_rss_bytes": 0,
                    },
                }
            )

    def close(self) -> None:
        pass

    def cancel(self, request_id: str) -> None:
        pass


class FixedRuntime:
    def inspect(self) -> Capability:
        return Capability(True, None, "1.0.0", installation_id="fixed-numeric-fixture")

    def selection(self, version: str, *, installation_id: str | None = None) -> Capability:
        return self.inspect()

    def worker(self, selected: Capability, *, cache_root: Path) -> FixedWorker:
        return FixedWorker(cache_root)


def create(root: Path) -> None:
    if root.exists():
        raise ValueError("Use a new external fixture directory")
    root.mkdir(parents=True)
    (root / "shop.yaml").write_text("etsy: {currency: USD}", encoding="utf-8")
    workspace = Workspace.discover(root_override=root)
    store = CalibrationStore(workspace)
    yy, xx = np.mgrid[:2048, :2048]
    noise = np.random.default_rng(2026).integers(0, 5, (2048, 2048))
    shade = (70 + 12 * np.sin(xx / 87) + 10 * np.cos(yy / 103) + noise).astype(np.uint8)
    photo = Image.fromarray(np.stack([shade, shade + 7, shade + 13], -1))
    for name, multiple in [("folded-bay", False), ("multiple-validation", True)]:
        directory = workspace.template_dir(name)
        directory.mkdir(parents=True)
        photo.save(directory / "scene.png")
        box = [{"x": x, "y": y} for x, y in [(560, 560), (1488, 560), (1488, 1488), (560, 1488)]]
        config: dict[str, Any] = {
            "kind": "multiple" if multiple else "single",
            "renderer": {"type": "marigold", "config": {}},
        }
        if multiple:
            config["placements"] = [
                {
                    "id": key,
                    "colour": "Navy",
                    "bounding_box": [
                        {"x": x, "y": y}
                        for x, y in [
                            (left, 560),
                            (left + 700, 560),
                            (left + 700, 1488),
                            (left, 1488),
                        ]
                    ],
                }
                for key, left in [("outer-white", 200), ("inner-magenta", 1148)]
            ]
        else:
            config["bounding_box"] = box
        workspace.save_template_config(name, load_template_config(config))
        for identity in store.placement_ids(store.config(name)):
            store.install_automatic(
                name,
                store.encode_mask(Image.new("L", (2048, 2048), 255)),
                algorithm_version="fixed-all-visible-v1",
                expected_revision=store.read(name).revision,
                placement_id=identity,
            )
    workspace.test_designs_dir().mkdir(parents=True)
    Image.new("RGBA", (512, 512), (255, 255, 255, 255)).save(
        workspace.test_design_file("benchmark-white")
    )
    coordinator = Preparations(workspace, runtime=FixedRuntime())
    coordinator.start()
    try:
        for name in ["folded-bay", "multiple-validation"]:
            job = coordinator.submit(
                name, config_revision=store.read(name).revision, request_id="fixed-" + name
            )
            deadline = time.monotonic() + 600
            while (job := coordinator.status(job.id)).phase not in TERMINAL:
                if time.monotonic() > deadline:
                    raise TimeoutError("Fixture preparation exceeded deadline")
                time.sleep(0.05)
            if job.phase != "completed":
                raise RuntimeError(job.error or job.phase)
            print(name + " fixed predictions prepared", flush=True)
    finally:
        coordinator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    create(parser.parse_args().root)

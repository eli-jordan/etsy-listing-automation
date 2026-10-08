"""Validate every real-resolution placement, overlap order and CPU/GPU overlap.

The scene deliberately places two prints on one real shirt. It proves map
completeness/composition, not a photographed two-garment setup or ground truth.
Use the external output produced by validate_marigold.py after it finishes.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import TERMINAL
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.numerics import EvidenceIdentity, evidence_covers, plan_crop
from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.render import MaterialLayer, render_marigold_scene
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


def host_memory(pid: int | None = None) -> dict[str, int]:
    """Native process working set and private commit, including peak values."""

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in [
                "peak_working_set",
                "working_set",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "commit",
                "peak_commit",
                "private",
            ]
        ]

    value = Counters()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    handle = kernel.GetCurrentProcess() if pid is None else kernel.OpenProcess(0x0410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if pid is not None:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
    return {
        name: int(getattr(value, name))
        for name in ["peak_working_set", "working_set", "commit", "peak_commit", "private"]
    }


def run(output: Path) -> None:
    workspace = Workspace.discover(root_override=output / "workspace")
    reference = workspace.root / "mockup-templates/fence-ivory"
    original = yaml.safe_load((reference / "template.yaml").read_text(encoding="utf-8"))
    box = np.array([[p["x"], p["y"]] for p in original["bounding_box"]], np.float32)
    centre = box.mean(axis=0)
    small = centre + (box - centre) * 0.6
    name = "multiple-validation"
    directory = workspace.root / "mockup-templates" / name
    directory.mkdir()
    shutil.copyfile(reference / "scene.png", directory / "scene.png")
    config = {
        "kind": "multiple",
        "placements": [
            {"id": "outer-white", "colour": "Ivory", "bounding_box": original["bounding_box"]},
            {
                "id": "inner-magenta",
                "colour": "Ivory",
                "bounding_box": [{"x": float(x), "y": float(y)} for x, y in small],
            },
        ],
        "renderer": {"type": "marigold", "config": {}},
    }
    (directory / "template.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    report: dict = {
        "provenance": "two overlapping prints on one copied real shirt",
        "status_latency_seconds": [],
    }
    coordinator = Preparations(workspace)
    coordinator.start()
    try:
        started = time.perf_counter()
        job = coordinator.submit(
            name,
            config_revision=CalibrationStore(workspace).read(name).revision,
            request_id="multiple-native-validation",
        )
        deadline = time.monotonic() + 900
        normals_started = None
        cancel_requested = None
        while (job := coordinator.status(job.id)).phase not in TERMINAL:
            before = time.perf_counter()
            coordinator.status(job.id)
            report["status_latency_seconds"].append(time.perf_counter() - before)
            if time.monotonic() > deadline:
                coordinator.cancel(job.id)
                raise TimeoutError("Multiple preparation deadline exceeded")
            if job.step == "normals" and normals_started is None:
                normals_started = time.perf_counter()
            if (
                normals_started
                and not cancel_requested
                and time.perf_counter() - normals_started > 8
            ):
                before = time.perf_counter()
                coordinator.cancel(job.id)
                report["cancel_control_seconds"] = time.perf_counter() - before
                cancel_requested = time.perf_counter()
            time.sleep(0.25)
        report["cancelled_job"] = job.model_dump(mode="json")
        report["cancel_to_terminal_seconds"] = (
            time.perf_counter() - cancel_requested if cancel_requested else None
        )
        if job.phase != "cancelled" or not any(v.predictions for v in job.evidence):
            raise RuntimeError("Native cancellation did not retain active-call evidence")
        job = coordinator.submit(
            name,
            config_revision=CalibrationStore(workspace).read(name).revision,
            request_id="multiple-native-retry",
            action="retry",
            previous_job=job.id,
        )
        deadline = time.monotonic() + 900
        while (job := coordinator.status(job.id)).phase not in TERMINAL:
            if time.monotonic() > deadline:
                coordinator.cancel(job.id)
                raise TimeoutError("Multiple native retry exceeded deadline")
            time.sleep(0.25)
        report["prepare_seconds"] = time.perf_counter() - started
        report["job"] = job.model_dump(mode="json")
        if job.phase != "completed":
            raise RuntimeError(job.error or job.phase)
    finally:
        coordinator.close()
    artifacts = Artifacts(workspace)
    with Image.open(directory / "scene.png") as image:
        base = np.array(image.convert("RGB"))
    designs = [
        np.full((512, 512, 4), 255, np.uint8),
        np.tile(np.array([255, 0, 255, 255], np.uint8), (512, 512, 1)),
    ]
    with artifacts.acquire(name, artifacts.saved_inputs(name)) as acquired:
        assert set(acquired.maps) == {"outer-white", "inner-magenta"}
        layers = [
            MaterialLayer(design, acquired.maps[key], key)
            for key, design in zip(["outer-white", "inner-magenta"], designs, strict=True)
        ]
        started = time.perf_counter()
        forward = render_marigold_scene(base, layers)
        report["render_seconds"] = time.perf_counter() - started
        reverse = render_marigold_scene(base, list(reversed(layers)))
        forward.save(output / "renders/multiple-forward.png")
        reverse.save(output / "renders/multiple-reverse.png")
        report["order_changed_pixels"] = int(
            np.any(np.array(forward) != np.array(reverse), axis=-1).sum()
        )
        report["complete_placements"] = list(acquired.maps)
        # A real model call runs while CPU rendering uses accepted maps.
        runtime = Runtime()
        cache = output / "overlap"
        cache.mkdir()
        shutil.copyfile(directory / "scene.png", cache / "photo.png")
        worker = runtime.worker(runtime.inspect(), cache_root=cache)
        measurement = {}

        def infer() -> None:
            started = time.perf_counter()
            try:
                measurement["result"] = worker.infer(
                    request_id="overlap",
                    role="depth",
                    input="photo.png",
                    output="depth.npz",
                    size=(2048, 2048),
                )
            except Exception as exc:
                measurement["error"] = str(exc)
            measurement["seconds"] = time.perf_counter() - started

        thread = threading.Thread(target=infer)
        try:
            thread.start()
            time.sleep(8)
            started = time.perf_counter()
            render_marigold_scene(base, layers)
            measurement["cpu_render_seconds"] = time.perf_counter() - started
            thread.join(timeout=930)
            measurement["finished"] = not thread.is_alive()
        finally:
            worker.close()
        report["cpu_gpu_overlap"] = measurement
        report["host_memory_after_overlap"] = host_memory()
        import cv2

        report["opencv_threads"] = cv2.getNumThreads()
        report["cpu_host_torch_installed"] = importlib.util.find_spec("torch") is not None
        report["cpu_host_torch_loaded"] = "torch" in sys.modules
    identity = EvidenceIdentity("photo", "checkpoint", "settings", "preprocessing")
    crop = plan_crop(box, (2048, 2048))
    report["reuse"] = {
        "rectangle": crop.rectangle,
        "original": evidence_covers(crop, identity, box, (2048, 2048), identity),
        "smaller": evidence_covers(crop, identity, small, (2048, 2048), identity),
        "shift_one_pixel": evidence_covers(crop, identity, box + 1, (2048, 2048), identity),
    }
    (output / "multiple.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)

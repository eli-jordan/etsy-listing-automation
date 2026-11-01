"""Native call/cancel/caps/shutdown measurements using the production runtime.

Use an existing external validation output directory from validate_marigold.py.
Raw predictions, photographs and model weights are never committed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.preparation.worker_client import InferenceCall, WorkerError

# Past the worker's 300 s idle exit (marigold_worker.server.serve), so the
# next call has to restart it.
IDLE_WAIT_S = 305


CALLS = [
    ("real", "depth", (2048, 2048)),
    ("real", "depth", (2048, 2048)),
    ("cap-4097", "depth", (4097, 4097)),
    ("cap-4096", "normals", (4096, 4096)),
    ("cap-4096", "lighting", (4096, 4096)),
    ("cap-4096", "depth", (4096, 4096)),
]
INVALID_SETTINGS = [(0, 3), (11, 3), (10, 0), (10, 4)]


class _Report:
    """The measurements, saved after each phase."""

    def __init__(self, path: Path) -> None:
        self.data: dict = {"target": "production Runtime.worker", "calls": []}
        self.path = path

    def save(self) -> None:
        # Worker replies are protocol models.
        text = json.dumps(self.data, indent=2, default=lambda reply: reply.model_dump(mode="json"))
        self.path.write_text(text + "\n", encoding="utf-8")


def _write_inputs(output: Path, cache: Path) -> None:
    with Image.open(output / "workspace/mockup-templates/fence-ivory/scene.png") as photo:
        photo.convert("RGB").save(cache / "real.png")
    for size in [4097, 4096]:
        Image.new("RGB", (size, size), (120, 140, 160)).save(cache / f"cap-{size}.png")


def _call(worker: Any, request: str, name: str, role: str, size: tuple[int, int]) -> dict:
    started = time.perf_counter()
    try:
        result = worker.infer(
            InferenceCall(
                request_id=request,
                role=role,
                input=name + ".png",
                output=request + ".npz",
                size=size,
            )
        )
    except WorkerError as exc:
        outcome = {"error": str(exc)}
    else:
        outcome = {"result": result}
    return {"request": request, "size": size, "seconds": time.perf_counter() - started, **outcome}


def _cancellation(worker: Any) -> dict:
    cancellation = {}

    def active() -> None:
        started = time.perf_counter()
        try:
            cancellation["result"] = worker.infer(
                InferenceCall(
                    request_id="cancel-real",
                    role="depth",
                    input="real.png",
                    output="cancel-real.npz",
                    size=(2048, 2048),
                )
            )
        except Exception as exc:  # noqa: BLE001 -- measurement boundary; record any failure in the report
            cancellation["error"] = str(exc)
        cancellation["call_seconds"] = time.perf_counter() - started

    thread = threading.Thread(target=active)
    thread.start()
    time.sleep(1)
    started = time.perf_counter()
    worker.cancel("cancel-real")
    cancellation["control_seconds"] = time.perf_counter() - started
    thread.join(timeout=930)
    cancellation["cancel_to_completion_seconds"] = time.perf_counter() - started
    cancellation["finished"] = not thread.is_alive()
    return cancellation


def _native_peak_memory(cache: Path) -> dict:
    modules = {}
    for name in ["multiple", "watchdog"]:
        spec = importlib.util.spec_from_file_location(
            name,
            Path(__file__).with_name("validate_marigold_" + name + ".py"),
        )
        assert spec
        assert spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules["multiple"].host_memory(modules["watchdog"].owned_pid(cache))


def _idle_restart(worker: Any, report: dict) -> None:
    idle_started = time.perf_counter()
    while time.perf_counter() - idle_started < IDLE_WAIT_S:
        time.sleep(5)
    restarted = time.perf_counter()
    report["after_default_idle"] = worker.infer(
        InferenceCall(
            request_id="after-idle",
            role="depth",
            input="real.png",
            output="after-idle.npz",
            size=(2048, 2048),
        )
    )
    report["idle_wait_seconds"] = restarted - idle_started
    report["idle_restart_call_seconds"] = time.perf_counter() - restarted


def _invalid_setting(worker: Any, steps: int, ensemble: int) -> dict:
    try:
        worker.infer(
            InferenceCall(
                request_id=f"invalid-{steps}-{ensemble}",
                role="depth",
                input="real.png",
                output=f"invalid-{steps}-{ensemble}.npz",
                size=(2048, 2048),
                num_inference_steps=steps,
                ensemble_size=ensemble,
            )
        )
    # The request model refuses these before anything reaches the worker.
    except (WorkerError, ValueError) as exc:
        return {"steps": steps, "ensemble": ensemble, "error": str(exc)}
    return {"steps": steps, "ensemble": ensemble, "unexpected_success": True}


def _settings(worker: Any, report: dict) -> None:
    report["minimum_settings"] = worker.infer(
        InferenceCall(
            request_id="minimum",
            role="depth",
            input="real.png",
            output="minimum.npz",
            size=(2048, 2048),
            num_inference_steps=1,
            ensemble_size=1,
        )
    )
    for steps, ensemble in INVALID_SETTINGS:
        report.setdefault("invalid_settings", []).append(_invalid_setting(worker, steps, ensemble))


def _measure(worker: Any, output: Path, cache: Path, report: _Report) -> None:
    _write_inputs(output, cache)
    for name, role, size in CALLS:
        request = f"call-{len(report.data['calls'])}"
        report.data["calls"].append(_call(worker, request, name, role, size))
        print(report.data["calls"][-1], flush=True)
        report.save()
    report.data["cancellation"] = _cancellation(worker)
    report.data["native_peak_memory"] = _native_peak_memory(cache)
    report.save()
    _idle_restart(worker, report.data)
    _settings(worker, report.data)
    report.save()


def run(output: Path) -> None:
    cache = output / "lifecycle"
    cache.mkdir(exist_ok=True)
    report = _Report(output / "lifecycle.json")
    runtime = Runtime()
    capability = runtime.inspect()
    worker = runtime.worker(capability, cache_root=cache)
    try:
        _measure(worker, output, cache, report)
    finally:
        started = time.perf_counter()
        worker.close()
        report.data["shutdown_seconds"] = time.perf_counter() - started
        report.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.output)

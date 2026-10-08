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

from PIL import Image

from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.preparation.worker_client import WorkerError


def run(output: Path) -> None:
    cache = output / "lifecycle"
    cache.mkdir(exist_ok=True)
    report: dict = {"target": "production Runtime.worker", "calls": []}
    path = output / "lifecycle.json"

    def save() -> None:
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    runtime = Runtime()
    capability = runtime.inspect()
    worker = runtime.worker(capability, cache_root=cache)
    try:
        with Image.open(output / "workspace/mockup-templates/fence-ivory/scene.png") as photo:
            photo.convert("RGB").save(cache / "real.png")
        for size in [4097, 4096]:
            Image.new("RGB", (size, size), (120, 140, 160)).save(cache / f"cap-{size}.png")
        for name, role, size in [
            ("real", "depth", (2048, 2048)),
            ("real", "depth", (2048, 2048)),
            ("cap-4097", "depth", (4097, 4097)),
            ("cap-4096", "normals", (4096, 4096)),
            ("cap-4096", "lighting", (4096, 4096)),
            ("cap-4096", "depth", (4096, 4096)),
        ]:
            request = f"call-{len(report['calls'])}"
            started = time.perf_counter()
            try:
                result = worker.infer(
                    request_id=request,
                    role=role,
                    input=name + ".png",
                    output=request + ".npz",
                    size=size,
                )
                report["calls"].append(
                    {
                        "request": request,
                        "size": size,
                        "seconds": time.perf_counter() - started,
                        "result": result,
                    }
                )
            except WorkerError as exc:
                report["calls"].append(
                    {
                        "request": request,
                        "size": size,
                        "seconds": time.perf_counter() - started,
                        "error": str(exc),
                    }
                )
            print(report["calls"][-1], flush=True)
            save()
        cancellation = {}

        def active() -> None:
            started = time.perf_counter()
            try:
                cancellation["result"] = worker.infer(
                    request_id="cancel-real",
                    role="depth",
                    input="real.png",
                    output="cancel-real.npz",
                    size=(2048, 2048),
                )
            except Exception as exc:
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
        report["cancellation"] = cancellation
        modules = {}
        for name in ["multiple", "watchdog"]:
            spec = importlib.util.spec_from_file_location(
                name,
                Path(__file__).with_name("validate_marigold_" + name + ".py"),
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules[name] = module
        report["native_peak_memory"] = modules["multiple"].host_memory(
            modules["watchdog"].owned_pid(cache),
        )
        save()
        idle_started = time.perf_counter()
        while time.perf_counter() - idle_started < 305:
            time.sleep(5)
        restarted = time.perf_counter()
        report["after_default_idle"] = worker.infer(
            request_id="after-idle",
            role="depth",
            input="real.png",
            output="after-idle.npz",
            size=(2048, 2048),
        )
        report["idle_wait_seconds"] = restarted - idle_started
        report["idle_restart_call_seconds"] = time.perf_counter() - restarted
        report["minimum_settings"] = worker.infer(
            request_id="minimum",
            role="depth",
            input="real.png",
            output="minimum.npz",
            size=(2048, 2048),
            num_inference_steps=1,
            ensemble_size=1,
        )
        for steps, ensemble in [(0, 3), (11, 3), (10, 0), (10, 4)]:
            try:
                worker.infer(
                    request_id=f"invalid-{steps}-{ensemble}",
                    role="depth",
                    input="real.png",
                    output=f"invalid-{steps}-{ensemble}.npz",
                    size=(2048, 2048),
                    num_inference_steps=steps,
                    ensemble_size=ensemble,
                )
                report.setdefault("invalid_settings", []).append(
                    {"steps": steps, "ensemble": ensemble, "unexpected_success": True}
                )
            except WorkerError as exc:
                report.setdefault("invalid_settings", []).append(
                    {"steps": steps, "ensemble": ensemble, "error": str(exc)}
                )
        save()
    finally:
        started = time.perf_counter()
        worker.close()
        report["shutdown_seconds"] = time.perf_counter() - started
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.output)

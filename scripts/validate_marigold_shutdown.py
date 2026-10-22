"""Measure production worker's 15s grace-to-force shutdown on native Windows.

Uses the watchdog driver's exact owned-backend discovery. Suspension models a
nonresponsive process, not a physical driver failure. Coordinator close is a
separate graceful-active-phase policy and is not assigned this 15s guarantee.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from PIL import Image

from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.preparation.worker_client import SHUTDOWN_TIMEOUT


def run(output: Path) -> None:
    cache = output / ("shutdown-native-cache-" + uuid4().hex)
    cache.mkdir()
    Image.new("RGB", (2048, 2048), (130, 150, 170)).save(cache / "photo.png")
    spec = importlib.util.spec_from_file_location(
        "watchdog", Path(__file__).with_name("validate_marigold_watchdog.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = Runtime()
    worker = runtime.worker(runtime.inspect(), cache_root=cache)
    report: dict = {
        "shutdown_grace_seconds": SHUTDOWN_TIMEOUT,
        "fault": "owned native backend suspended",
    }
    suspended = threading.Event()
    pid = None

    def suspend(progress: dict) -> None:
        nonlocal pid
        if pid is not None:
            return
        pid = module.owned_pid(cache)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        handle = kernel.OpenProcess(0x0800, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            native = ctypes.WinDLL("ntdll")
            native.NtSuspendProcess.argtypes = [ctypes.c_void_p]
            if status := native.NtSuspendProcess(handle):
                raise RuntimeError(f"Native suspend failed: {status}")
        finally:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
        suspended.set()

    def active() -> None:
        try:
            worker.infer(
                request_id="shutdown",
                role="depth",
                input="photo.png",
                output="depth.npz",
                size=(2048, 2048),
                progress=suspend,
            )
            report["unexpected_success"] = True
        except Exception as exc:
            report["call_error"] = str(exc)

    thread = threading.Thread(target=active)
    try:
        thread.start()
        if not suspended.wait(timeout=120):
            raise RuntimeError("Native owned process was not suspended within startup deadline")
        started = time.perf_counter()
        worker.close()
        report["shutdown_seconds"] = time.perf_counter() - started
        thread.join(timeout=30)
        report["active_call_finished"] = not thread.is_alive()
    finally:
        if pid is not None:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                timeout=30,
                capture_output=True,
                check=False,
            )
        worker.close()
        report["artifact_exists"] = (cache / "depth.npz").exists()
        report["partial_artifacts"] = [p.name for p in cache.glob(".depth.npz.*")]
        (output / "shutdown.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)

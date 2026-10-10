"""Exercise the unshortened 900s watchdog with an owned suspended native worker.

The production runtime/worker executes startup and a native model call. Suspending
that process is a deliberate hung-process proxy, not a real CUDA driver fault.
WMIC verifies the exact unique cache command before any process control. Cleanup
kills only that verified process tree. Run separately while no other GPU call runs.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from PIL import Image

from etsy_listings.core.preparation.runtime import Runtime
from etsy_listings.core.preparation.worker_client import CALL_TIMEOUT, WorkerError


def owned_pid(cache: Path) -> int:
    listing = subprocess.check_output(
        [
            "wmic",
            "process",
            "where",
            "name='python.exe'",
            "get",
            "ProcessId,ParentProcessId,CommandLine",
            "/format:csv",
        ],
        text=True,
        errors="replace",
        timeout=30,
    )
    rows = csv.DictReader(listing.strip().splitlines())
    matches = {
        int(row["ProcessId"]): int(row.get("ParentProcessId") or 0)
        for row in rows
        if "-m marigold_worker" in (row.get("CommandLine") or "")
        and str(cache.resolve()).casefold() in (row.get("CommandLine") or "").casefold()
    }
    leaves = set(matches) - set(matches.values())
    if len(leaves) != 1:
        raise RuntimeError(f"Expected one owned native backend; found {len(leaves)}")
    leaf = next(iter(leaves))
    visited = set()
    current = leaf
    while current in matches and current not in visited:
        visited.add(current)
        current = matches[current]
    if visited != set(matches):
        raise RuntimeError("Owned native process matches are not one verified launcher chain")
    return leaf


def run(output: Path) -> None:
    cache = output / ("watchdog-native-cache-" + uuid4().hex)
    cache.mkdir()
    Image.new("RGB", (2048, 2048), (130, 150, 170)).save(cache / "photo.png")
    runtime = Runtime()
    worker = runtime.worker(runtime.inspect(), cache_root=cache)
    report: dict = {"watchdog_seconds": CALL_TIMEOUT, "fault": "owned native worker suspended"}
    pid = None
    suspended_at = None
    started = time.perf_counter()

    def suspend(progress: dict) -> None:
        nonlocal pid, suspended_at
        if pid is not None:
            return
        pid = owned_pid(cache)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        handle = kernel.OpenProcess(0x0800, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            native = ctypes.WinDLL("ntdll")
            native.NtSuspendProcess.argtypes = [ctypes.c_void_p]
            status = native.NtSuspendProcess(handle)
            if status:
                raise RuntimeError(f"NtSuspendProcess failed with {status}")
        finally:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
        suspended_at = time.perf_counter()
        report["pid"] = pid
        report["progress_before_suspend"] = progress
        print("Suspended owned worker", pid, "for default 900s watchdog", flush=True)

    try:
        worker.infer(
            request_id="native-watchdog",
            role="depth",
            input="photo.png",
            output="depth.npz",
            size=(2048, 2048),
            progress=suspend,
        )
        report["unexpected_success"] = True
    except WorkerError as exc:
        report["error"] = str(exc)
    finally:
        report["call_seconds"] = time.perf_counter() - started
        if suspended_at is not None:
            report["suspend_to_return_seconds"] = time.perf_counter() - suspended_at
        before = time.perf_counter()
        worker.close()
        report["close_seconds"] = time.perf_counter() - before
        if pid is not None:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                timeout=30,
                check=False,
                capture_output=True,
            )
        report["final_artifact_exists"] = (cache / "depth.npz").exists()
        report["partial_artifacts"] = [p.name for p in cache.glob(".depth.npz.*")]
        (output / "watchdog.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)

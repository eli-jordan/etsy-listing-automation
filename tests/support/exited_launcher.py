"""Real exited-launcher fixtures. Cleanup uses pinned OS identities, never names."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import select
import shlex
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _kernel() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    api.OpenProcess.restype = ctypes.c_void_p
    api.GetProcessTimes.argtypes = [ctypes.c_void_p, *([ctypes.c_void_p] * 4)]
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    return api


def _identity(pid: int) -> dict[str, int | str]:
    if sys.platform == "win32":
        api = _kernel()
        handle = api.OpenProcess(0x1000, False, pid)
        try:
            created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
            if not api.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return {"pid": pid, "created": created.value}
        finally:
            api.CloseHandle(handle)
    return {
        "pid": pid,
        "created": Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19],
    }


class ProcessRef:
    def __init__(self, record: dict[str, Any]):
        self.pid = int(record["pid"])
        if sys.platform == "win32":
            self.api = _kernel()
            self.handle = self.api.OpenProcess(0x100001 | 0x1000, False, self.pid)
            assert self.handle
        else:
            self.handle = os.pidfd_open(self.pid)
        assert _identity(self.pid) == record, "the fixture process identity changed before pinning"

    def wait(self, seconds: float = 0) -> bool:
        if sys.platform == "win32":
            return self.api.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0
        return bool(select.select([self.handle], [], [], seconds)[0])

    def close(self) -> None:
        if sys.platform == "win32":
            self.api.CloseHandle(self.handle)
        else:
            os.close(self.handle)

    def kill(self) -> None:
        if sys.platform == "win32":
            if not self.api.TerminateProcess(self.handle, 1) and not self.wait():
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(self.handle, signal.SIGKILL)


class ExitedLauncher:
    def __init__(self, root: Path, *, captured_pipes: bool = True, returncode: int = 0):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.refs: dict[str, ProcessRef] = {}
        self.before = set(threading.enumerate())
        self.started = time.monotonic()
        source = Path(__file__).resolve()
        arguments = [
            # Windows venv python.exe is itself a redirector process. Using
            # the base interpreter makes this script's parent the actual CMD
            # launcher owned by run_managed, rather than that intermediary.
            sys._base_executable,
            str(source),
            "launcher",
            str(root),
            str(int(captured_pipes)),
            str(returncode),
        ]
        if sys.platform == "win32":
            import subprocess

            self.command = root / "synthetic.cmd"
            self.command.write_text(
                "@" + subprocess.list2cmdline(arguments) + "\r\n", encoding="utf-8"
            )
        else:
            self.command = root / "synthetic"
            self.command.write_text(
                "#!/bin/sh\nexec " + shlex.join(arguments) + "\n", encoding="utf-8"
            )
            self.command.chmod(0o755)

    def exited(self) -> bool:
        if not self.refs and all(
            (self.root / f"{name}.json").exists() for name in ("launcher", "child")
        ):
            for name in ("launcher", "child"):
                self.refs[name] = ProcessRef(json.loads((self.root / f"{name}.json").read_text()))
            (self.root / "ack").touch()
            assert self.refs["launcher"].wait(5), "the acknowledged launcher did not exit"
        return bool(self.refs) and self.refs["launcher"].wait()

    def readers(self) -> list[threading.Thread]:
        return [thread for thread in threading.enumerate() if thread not in self.before]

    def assert_clean(self) -> None:
        assert self.exited(), "the launcher must have exited before cleanup"
        assert self.refs["child"].wait(1), "the descendant survived managed cleanup"
        size = (self.root / "heartbeat").stat().st_size
        time.sleep(0.15)
        assert (self.root / "heartbeat").stat().st_size == size
        assert not self.readers(), "managed pipe readers survived return"

    def __enter__(self) -> ExitedLauncher:
        return self

    def __exit__(self, *args: object) -> None:
        (self.root / "stop").touch()
        (self.root / "ack").touch()
        try:
            for ref in self.refs.values():
                if not ref.wait(5):
                    ref.kill()
                assert ref.wait(5), "a synthetic process did not stop during finally cleanup"
            for thread in self.readers():
                thread.join(5)
            assert not self.readers(), "a reader outlived fixture cleanup"
        finally:
            for ref in self.refs.values():
                ref.close()


def _main() -> None:
    import subprocess

    mode, directory = sys.argv[1:3]
    root = Path(directory)
    if mode == "child":
        _record(root, "child", os.getpid())
        until = time.monotonic() + 30
        while not (root / "stop").exists() and time.monotonic() < until:
            with (root / "heartbeat").open("a") as stream:
                stream.write("x")
            time.sleep(0.02)
        return
    capture, code = map(int, sys.argv[3:5])
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "child", str(root)],
        stdin=subprocess.DEVNULL,
        stdout=None if capture else subprocess.DEVNULL,
        stderr=None if capture else subprocess.DEVNULL,
    )
    pid = os.getppid() if sys.platform == "win32" else os.getpid()
    _record(root, "launcher", pid)
    until = time.monotonic() + 15
    while not (root / "ack").exists() and time.monotonic() < until:
        time.sleep(0.01)
    print(
        json.dumps({"models": [{"slug": "synthetic", "supported_reasoning_levels": []}]}),
        flush=True,
    )
    sys.exit(code)


def _record(root: Path, name: str, pid: int) -> None:
    temporary = root / f"{name}.tmp"
    temporary.write_text(json.dumps(_identity(pid)))
    temporary.replace(root / f"{name}.json")


if __name__ == "__main__":
    _main()

"""Reserve a session leader until cleanup, including after launcher exit."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO, cast


class PosixProcess:
    def __init__(self, argv: Sequence[str], cwd: Path) -> None:
        self.proc = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        self.stdin = cast(TextIO, self.proc.stdin)
        self.stdout = cast(TextIO, self.proc.stdout)
        self.stderr = cast(TextIO, self.proc.stderr)

    @property
    def exited(self) -> bool:
        if hasattr(os, "waitid"):
            return (
                os.waitid(
                    os.__dict__["P_PID"],
                    self.proc.pid,
                    os.__dict__["WEXITED"] | os.__dict__["WNOHANG"] | os.__dict__["WNOWAIT"],
                )
                is not None
            )
        # Python 3.12 lacks os.waitid on macOS although libc supports it.
        # siginfo_t starts with si_signo on Darwin; a zeroed buffer stays zero
        # when WNOHANG finds no exit. WNOWAIT leaves the leader unreaped.
        if sys.platform != "darwin":
            raise OSError("managed process ownership requires waitid with WNOWAIT")
        libc = ctypes.CDLL(None, use_errno=True)
        info = (ctypes.c_int * 32)()
        if libc.waitid(1, self.proc.pid, ctypes.byref(info), 0x4 | 0x1 | 0x20) != 0:
            raise OSError(ctypes.get_errno(), "waitid failed")
        return info[0] != 0

    def kill(self) -> None:
        # An unreaped leader reserves both PID and PGID. Never rediscover the
        # group through a launcher PID which may already have disappeared.
        os.__dict__["killpg"](self.proc.pid, signal.__dict__["SIGKILL"])

    def wait(self, timeout: float) -> int:
        return self.proc.wait(timeout=timeout)

    def close(self) -> None:
        pass

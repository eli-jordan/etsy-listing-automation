"""Own a CLI's processes and pipes until every captured stream is drained.

Windows uses an atomically assigned kill-on-close job. POSIX reserves a new
session's leader until group termination, observing exit without reaping it.
Cleanup never depends on finding a live launcher or scanning descendant PIDs.
Adapters and discovery share this owner and know no platform-specific policy.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from etsy_listings.core.ai.models import Deadline

# Chosen once, at import: the other platform's module is never imported.
if sys.platform == "win32":
    from etsy_listings.core.ai._windows_process import WindowsProcess as _OwnedProcess
else:
    from etsy_listings.core.ai._posix_process import PosixProcess as _OwnedProcess

POLL_INTERVAL = 0.05
"""How often the wait loop checks the deadline, cancellation and exit. Read at
each call rather than bound as a default, so a test can shorten it."""
_REAP_TIMEOUT = 5.0


class CliProcessError(RuntimeError):
    """A command could not be launched, safely owned, or cleaned up."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    cancelled: bool


class _Capture:
    def __init__(self, stdin: TextIO, stdout: TextIO, stderr: TextIO, text: str) -> None:
        self.stdin, self.stdout, self.stderr, self.text = stdin, stdout, stderr, text
        self.output: dict[str, str] = {}
        self.errors: list[Exception] = []
        self.worker = threading.Thread(
            target=self._communicate, name="ai-process-pipes", daemon=True
        )

    def _read(self, name: str, stream: TextIO) -> None:
        try:
            self.output[name] = stream.read()
        except (OSError, ValueError) as exc:
            self.errors.append(exc)
        finally:
            stream.close()

    def _communicate(self) -> None:
        readers = [
            threading.Thread(
                target=self._read, args=(name, stream), name=f"ai-process-{name}", daemon=True
            )
            for name, stream in (("stdout", self.stdout), ("stderr", self.stderr))
        ]
        for reader in readers:
            reader.start()
        try:
            self.stdin.write(self.text)
        except (OSError, ValueError) as exc:
            self.errors.append(exc)
        finally:
            with contextlib.suppress(OSError):
                self.stdin.close()
        for reader in readers:
            reader.join()


def run_managed(
    argv: Sequence[str],
    *,
    cwd: Path,
    input_text: str,
    deadline: Deadline,
    cancel_event: threading.Event | None = None,
) -> ProcessResult:
    """Run a command within its deadline and cancellation signal.

    Normal/error completion also ends remaining descendants. Exit is observed
    separately from pipe EOF: an exited launcher cannot abandon pipe readers.
    The five-second cleanup allowance covers termination, drain and reaping.
    """
    try:
        scope = _OwnedProcess(argv, cwd)
    except OSError as exc:
        raise CliProcessError(f"could not start and own {list(argv)!r}: {exc}") from exc

    capture = _Capture(scope.stdin, scope.stdout, scope.stderr, input_text)
    try:
        capture.worker.start()
        ending = _wait(scope, capture, deadline, cancel_event)
    finally:
        code = _clean_up(scope, capture)
    timed_out, cancelled = ending == "timed_out", ending == "cancelled"
    if capture.errors and not (timed_out or cancelled):
        errors = [error for error in capture.errors if not isinstance(error, BrokenPipeError)]
        if errors:
            raise CliProcessError(f"managed process I/O failed: {errors[0]}")
    return ProcessResult(
        code,
        capture.output.get("stdout", ""),
        capture.output.get("stderr", ""),
        timed_out,
        cancelled,
    )


type _Ending = Literal["exited", "timed_out", "cancelled"]


def _wait(
    scope: _OwnedProcess,
    capture: _Capture,
    deadline: Deadline,
    cancel_event: threading.Event | None,
) -> _Ending:
    """Poll until the command exits, its deadline passes or it is cancelled."""
    idle = cancel_event or threading.Event()
    while (ending := _ending(scope, deadline, cancel_event)) is None:
        if capture.worker.is_alive():
            capture.worker.join(POLL_INTERVAL)
        else:
            idle.wait(POLL_INTERVAL)
    return ending


def _ending(
    scope: _OwnedProcess, deadline: Deadline, cancel_event: threading.Event | None
) -> _Ending | None:
    """Why waiting is over, checked in this order, or None to keep waiting."""
    if cancel_event is not None and cancel_event.is_set():
        return "cancelled"
    if deadline.expired:
        return "timed_out"
    return "exited" if scope.exited else None


def _clean_up(scope: _OwnedProcess, capture: _Capture) -> int:
    """End every owned process and drain the pipes, within the cleanup
    allowance; the exit code once reaped."""
    reap_at = time.monotonic() + _REAP_TIMEOUT
    try:
        scope.kill()
        if capture.worker.ident is not None:
            capture.worker.join(max(0.0, reap_at - time.monotonic()))
        if capture.worker.is_alive():
            raise CliProcessError(
                "managed process pipe readers did not stop within cleanup allowance"
            )
        return scope.wait(max(0.0, reap_at - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CliProcessError(f"could not clean up managed processes: {exc}") from exc
    finally:
        scope.close()

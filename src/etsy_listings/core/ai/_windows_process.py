"""Windows 10+ process ownership, private to ``process``.

JOB_LIST assigns the new process before it can execute. Its job is retained
after launcher exit and is never inherited. HANDLE_LIST confines inheritance
to stdio. No process-name matching, descendant snapshot or helper is needed.
"""

from __future__ import annotations

import ctypes as c
import os
import subprocess
import time
from collections.abc import Sequence
from ctypes import wintypes as w
from pathlib import Path
from typing import Any, TextIO, cast


class _Limits(c.Structure):
    _fields_ = [
        ("process_time", c.c_int64),
        ("job_time", c.c_int64),
        ("flags", w.DWORD),
        ("min_working_set", c.c_size_t),
        ("max_working_set", c.c_size_t),
        ("active_processes", w.DWORD),
        ("affinity", c.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class _ExtendedLimits(c.Structure):
    _fields_ = [
        ("basic", _Limits),
        ("io_counters", c.c_uint64 * 6),
        ("process_memory", c.c_size_t),
        ("job_memory", c.c_size_t),
        ("peak_process_memory", c.c_size_t),
        ("peak_job_memory", c.c_size_t),
    ]


class _Startup(c.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("width", w.DWORD),
        ("height", w.DWORD),
        ("columns", w.DWORD),
        ("rows", w.DWORD),
        ("fill", w.DWORD),
        ("flags", w.DWORD),
        ("show", w.WORD),
        ("reserved_size", w.WORD),
        ("reserved_data", c.c_void_p),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class _StartupEx(c.Structure):
    _fields_ = [("startup", _Startup), ("attributes", c.c_void_p)]


class _ProcessInfo(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


class _Accounting(c.Structure):
    _fields_ = [
        ("times", c.c_int64 * 4),
        ("page_faults", w.DWORD),
        ("total", w.DWORD),
        ("active", w.DWORD),
        ("terminated", w.DWORD),
    ]


def _api() -> Any:
    api = c.__dict__["WinDLL"]("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        "InitializeProcThreadAttributeList": ([c.c_void_p, w.DWORD, w.DWORD, c.c_void_p], w.BOOL),
        "UpdateProcThreadAttribute": (
            [c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p],
            w.BOOL,
        ),
        "DeleteProcThreadAttributeList": ([c.c_void_p], None),
        "CreateProcessW": (
            [
                w.LPCWSTR,
                w.LPWSTR,
                c.c_void_p,
                c.c_void_p,
                w.BOOL,
                w.DWORD,
                c.c_void_p,
                w.LPCWSTR,
                c.c_void_p,
                c.c_void_p,
            ],
            w.BOOL,
        ),
        "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
        "QueryInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "GetExitCodeProcess": ([w.HANDLE, c.c_void_p], w.BOOL),
        "CloseHandle": ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def _checked(ok: object) -> None:
    if not ok:
        raise c.__dict__["WinError"](c.__dict__["get_last_error"]())


_KILL_ON_JOB_CLOSE = 0x2000
"""No breakaway flags: nothing the CLI starts can leave the job."""
_EXTENDED_LIMIT_INFORMATION = 9
_BASIC_ACCOUNTING_INFORMATION = 1
_ATTRIBUTE_HANDLE_LIST = 0x20002
_ATTRIBUTE_JOB_LIST = 0x2000D
_USE_STD_HANDLES = 0x100
_EXTENDED_STARTUPINFO_PRESENT = 0x80000
_NO_WINDOW = 0x8000000
_WAIT_TIMEOUT = 258
_INHERITABLE = True
"""Only the three stdio handles, and HANDLE_LIST confines inheritance to them."""


def _pipe(fds: set[int]) -> tuple[int, int]:
    """A new pipe, both ends recorded in ``fds`` until handed to a stream."""
    read, write = os.pipe()
    fds.update((read, write))
    return read, write


class WindowsProcess:
    def __init__(self, argv: Sequence[str], cwd: Path) -> None:
        command_line, directory = subprocess.list2cmdline(argv), str(cwd)
        if "\x00" in command_line or "\x00" in directory:
            raise ValueError("embedded null byte")
        self.api = _api()
        self.job = self.api.CreateJobObjectW(None, None)
        _checked(self.job)
        self.handle: int | None = None
        self.streams: list[TextIO] = []
        import msvcrt  # noqa: PLC0415 -- Windows-only: every core module is also imported on POSIX

        fds: set[int] = set()
        try:
            self._limit_job()
            stdin_read, stdin_write = _pipe(fds)
            stdout_read, stdout_write = _pipe(fds)
            stderr_read, stderr_write = _pipe(fds)
            handles = (w.HANDLE * 3)(
                *(
                    msvcrt.__dict__["get_osfhandle"](fd)
                    for fd in (stdin_read, stdout_write, stderr_write)
                )
            )
            for handle in handles:
                os.__dict__["set_handle_inheritable"](cast(int, handle), _INHERITABLE)
            self._create(command_line, directory, handles)
            for fd, mode in ((stdin_write, "w"), (stdout_read, "r"), (stderr_read, "r")):
                stream = cast(TextIO, os.fdopen(fd, mode, encoding="utf-8", errors="replace"))
                self.streams.append(stream)
                fds.remove(fd)
            self.stdin, self.stdout, self.stderr = self.streams
        except BaseException:
            self.close()
            for stream in self.streams:
                stream.close()
            raise
        finally:
            for fd in fds:
                os.close(fd)

    def _limit_job(self) -> None:
        limits = _ExtendedLimits()
        limits.basic.flags = _KILL_ON_JOB_CLOSE
        _checked(
            self.api.SetInformationJobObject(
                self.job, _EXTENDED_LIMIT_INFORMATION, c.byref(limits), c.sizeof(limits)
            )
        )

    def _create(self, command_line: str, directory: str, handles: Any) -> None:
        """Start the command already in the job, inheriting only ``handles``."""
        size = c.c_size_t()
        self.api.InitializeProcThreadAttributeList(None, 2, 0, c.byref(size))
        attributes = c.create_string_buffer(size.value)
        _checked(self.api.InitializeProcThreadAttributeList(attributes, 2, 0, c.byref(size)))
        try:
            jobs = (w.HANDLE * 1)(self.job)
            for attribute, value in (
                (_ATTRIBUTE_HANDLE_LIST, handles),
                (_ATTRIBUTE_JOB_LIST, jobs),
            ):
                _checked(
                    self.api.UpdateProcThreadAttribute(
                        attributes, 0, attribute, value, c.sizeof(value), None, None
                    )
                )
            startup = _StartupEx()
            startup.startup.size = c.sizeof(startup)
            startup.startup.flags = _USE_STD_HANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
            startup.attributes = c.cast(attributes, c.c_void_p)
            info = _ProcessInfo()
            command = c.create_unicode_buffer(command_line)
            _checked(
                self.api.CreateProcessW(
                    None,
                    command,
                    None,
                    None,
                    _INHERITABLE,
                    _EXTENDED_STARTUPINFO_PRESENT | _NO_WINDOW,
                    None,
                    directory,
                    c.byref(startup),
                    c.byref(info),
                )
            )
            self.handle = info.process
            self.api.CloseHandle(info.thread)
            self.pid = info.pid
        finally:
            self.api.DeleteProcThreadAttributeList(attributes)

    @property
    def exited(self) -> bool:
        result = self.api.WaitForSingleObject(self.handle, 0)
        if result == _WAIT_TIMEOUT:
            return False
        _checked(result == 0)
        return True

    def kill(self) -> None:
        _checked(self.api.TerminateJobObject(self.job, 1))

    def wait(self, timeout: float) -> int:
        until = time.monotonic() + timeout
        accounting = _Accounting()
        while True:
            _checked(
                self.api.QueryInformationJobObject(
                    self.job,
                    _BASIC_ACCOUNTING_INFORMATION,
                    c.byref(accounting),
                    c.sizeof(accounting),
                    None,
                )
            )
            if accounting.active == 0:
                break
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("managed process job", timeout)
            time.sleep(min(0.01, remaining))
        timeout = max(0.0, until - time.monotonic())
        result = self.api.WaitForSingleObject(self.handle, max(0, int(timeout * 1000)))
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("managed process", timeout)
        _checked(result == 0)
        code = w.DWORD()
        _checked(self.api.GetExitCodeProcess(self.handle, c.byref(code)))
        return code.value

    def close(self) -> None:
        if self.job is not None:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None

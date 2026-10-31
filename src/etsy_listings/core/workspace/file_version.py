"""Content-change tokens for in-process caches, never deployment input hashes.

Windows may give consecutive same-size writes identical timestamps. NTFS USNs
identify writes after the last writable handle closes. While another writer
is open, or on unsupported Windows filesystems, use a content hash. POSIX
change time cannot be restored by utime.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import cast


@lru_cache(maxsize=1)
def _kernel_api() -> ctypes.CDLL:
    # WinDLL uses the Windows calling convention but is absent from POSIX
    # ctypes stubs. The concrete instance is a CDLL subclass, loaded only on nt.
    api = cast(ctypes.CDLL, ctypes.__dict__["WinDLL"]("kernel32", use_last_error=True))
    api.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    api.CreateFileW.restype = ctypes.c_void_p
    api.DeviceIoControl.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    return api


def _windows_usn(path: Path) -> int | None:
    # FILE_READ_DATA | FILE_READ_ATTRIBUTES, share read/delete, OPEN_EXISTING.
    # Attribute-only handles bypass Windows sharing checks. USN reasons
    # coalesce while another writable handle remains open, so a USN alone
    # cannot detect every overwrite then. Denying write sharing for this short
    # metadata read proves quiescence; if another writer is open, fall back to
    # the content hash instead. Atomic replacement is still shared/allowed.
    api = _kernel_api()
    handle = api.CreateFileW(str(path), 0x81, 5, None, 3, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        return None
    try:
        buffer = ctypes.create_string_buffer(4096)
        returned = ctypes.c_uint32()
        # FSCTL_READ_FILE_USN_DATA with no input requests USN_RECORD_V2.
        # https://learn.microsoft.com/windows/win32/api/winioctl/ni-winioctl-fsctl_read_file_usn_data
        if not api.DeviceIoControl(
            handle, 0x900EB, None, 0, buffer, len(buffer), ctypes.byref(returned), None
        ):
            return None
        if returned.value < 32 or int.from_bytes(buffer.raw[4:6], "little") != 2:
            return None
        usn = int.from_bytes(buffer.raw[24:32], "little", signed=True)
        return usn if usn > 0 else None
    finally:
        api.CloseHandle(handle)


def file_version(path: Path) -> tuple[int | str, ...]:
    """Return a cache token that changes after a completed file modification."""
    stat = path.stat()
    stamp: tuple[int | str, ...] = (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    if os.name != "nt":
        return stamp
    usn = _windows_usn(path)
    if usn is not None:
        return (*stamp, usn)
    with path.open("rb") as stream:
        return (*stamp, hashlib.file_digest(stream, "sha256").hexdigest())

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
import sys
from functools import lru_cache
from pathlib import Path

# USN_RECORD_V2 (winioctl.h): the version this reads, and the header bytes
# up to and including its Usn field.
_USN_RECORD_V2 = 2
_USN_HEADER_BYTES = 32

# winioctl.h and winnt.h
_FSCTL_READ_FILE_USN_DATA = 0x900EB
_FILE_READ_DATA = 0x1
_FILE_READ_ATTRIBUTES = 0x80
_FILE_SHARE_READ = 0x1
_FILE_SHARE_DELETE = 0x4
_OPEN_EXISTING = 3


if sys.platform == "win32":

    @lru_cache(maxsize=1)
    def _kernel_api() -> ctypes.WinDLL:
        api = ctypes.WinDLL("kernel32", use_last_error=True)
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
        # Attribute-only handles bypass Windows sharing checks. USN reasons
        # coalesce while another writable handle remains open, so a USN alone
        # cannot detect every overwrite then. Denying write sharing for this short
        # metadata read proves quiescence; if another writer is open, fall back to
        # the content hash instead. Atomic replacement is still shared/allowed.
        api = _kernel_api()
        handle = api.CreateFileW(
            str(path),
            _FILE_READ_DATA | _FILE_READ_ATTRIBUTES,
            _FILE_SHARE_READ | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            return None
        try:
            buffer = ctypes.create_string_buffer(4096)
            returned = ctypes.c_uint32()
            # With no input buffer the ioctl answers a USN_RECORD_V2.
            # https://learn.microsoft.com/windows/win32/api/winioctl/ni-winioctl-fsctl_read_file_usn_data
            if not api.DeviceIoControl(
                handle,
                _FSCTL_READ_FILE_USN_DATA,
                None,
                0,
                buffer,
                len(buffer),
                ctypes.byref(returned),
                None,
            ):
                return None
            if (
                returned.value < _USN_HEADER_BYTES
                or int.from_bytes(buffer.raw[4:6], "little") != _USN_RECORD_V2
            ):
                return None
            usn = int.from_bytes(buffer.raw[24:32], "little", signed=True)
            return usn if usn > 0 else None
        finally:
            api.CloseHandle(handle)

    def _windows_version(path: Path, stamp: tuple[int | str, ...]) -> tuple[int | str, ...]:
        usn = _windows_usn(path)
        if usn is not None:
            return (*stamp, usn)
        with path.open("rb") as stream:
            return (*stamp, hashlib.file_digest(stream, "sha256").hexdigest())


TreeVersion = tuple[tuple[str, int, int], ...]


def tree_version(directory: Path) -> TreeVersion:
    """A cache token for everything under ``directory``: each file's path,
    size and modification time, from one stat-only walk.

    Far cheaper than :func:`file_version` per file -- a scan of a few hundred
    files costs milliseconds, where reading what they decide can cost a
    second -- at the price of its guarantee: a same-size rewrite inside one
    timestamp tick goes unseen. Use it only where an answer one such write
    late is harmless and the reader that acts on it re-reads the files.
    Symlinked directories are followed, once each, so a template aliased to
    another's files still sees them change. A directory that is missing, or
    an entry that vanishes mid-walk, simply contributes nothing.
    """
    found: list[tuple[str, int, int]] = []
    visited: set[tuple[int, int]] = set()
    pending = [directory]
    while pending:
        for entry in _unvisited_entries(pending.pop(), visited):
            _version_entry(entry, found, pending)
    return tuple(sorted(found))


def _unvisited_entries(directory: Path, visited: set[tuple[int, int]]) -> list[os.DirEntry[str]]:
    try:
        stat = directory.stat()
        if (stat.st_dev, stat.st_ino) in visited:
            return []
        visited.add((stat.st_dev, stat.st_ino))
        with os.scandir(directory) as entries:
            return list(entries)
    except OSError:
        return []


def _version_entry(
    entry: os.DirEntry[str], found: list[tuple[str, int, int]], pending: list[Path]
) -> None:
    try:
        if entry.is_dir():
            pending.append(Path(entry.path))
            return
        stat = entry.stat()
    except OSError:
        return
    found.append((entry.path, stat.st_size, stat.st_mtime_ns))


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
    if sys.platform == "win32":
        return _windows_version(path, stamp)
    return stamp

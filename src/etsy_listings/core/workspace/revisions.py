"""Revision-checked saves of a whole workspace file.

The lock is per path and per process. Another process writing the file is
caught by the hash, except in the milliseconds between the read and the
replace, which no Windows file lock would close for an editor that ignores it.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_bytes_atomic

__all__ = [
    "ABSENT_REVISION",
    "Revised",
    "RevisionConflictError",
    "content_revision",
    "read_revisioned",
    "replace_if_unchanged",
]


class RevisionConflictError(UserFacingError, RuntimeError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"{path.name} changed on disk since it was loaded; reload it first")
        self.path = path


@dataclass(frozen=True)
class Revised:
    revision: str
    """The file's revision after the save, which the next save must name."""
    written: bool


def content_revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


ABSENT_REVISION = "absent"
"""An ``absent_ok`` file's revision while it does not exist. Never a sha256."""


_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = path.resolve()
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def read_revisioned(path: Path, *, absent_ok: bool = False) -> tuple[bytes, str]:
    """Under the save lock, so the bytes and the hash come from one save."""
    with _lock_for(path):
        return _read(path, absent_ok=absent_ok)


def replace_if_unchanged(
    path: Path,
    expected_revision: str,
    change: Callable[[bytes], bytes],
    *,
    absent_ok: bool = False,
    adopt: Callable[[], None] | None = None,
) -> Revised:
    """``adopt`` runs inside the lock once the file holds the result, so
    publications happen in the order the saves reached the file."""
    with _lock_for(path):
        current, revision = _read(path, absent_ok=absent_ok)
        if revision != expected_revision:
            raise RevisionConflictError(path)
        edited = change(current)
        if edited == current:
            revised = Revised(expected_revision, written=False)
        else:
            write_bytes_atomic(path, edited)
            revised = Revised(content_revision(edited), written=True)
        if adopt is not None:
            adopt()
        return revised


def _read(path: Path, *, absent_ok: bool) -> tuple[bytes, str]:
    try:
        data = read_bytes_retrying(path)
    except FileNotFoundError:
        if not absent_ok:
            raise
        return b"", ABSENT_REVISION
    return data, content_revision(data)

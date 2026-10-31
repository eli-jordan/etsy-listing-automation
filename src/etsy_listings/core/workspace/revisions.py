"""Revision-checked saves of a whole workspace file: the Admin page's rule.

Admin plan, *Settled requirements*: a read returns a hash of the file's exact
bytes, and every save compares the hash it was made against under the same
lock as its read, change and atomic replace. A conflict never overwrites an
external edit, even a comment-only one; the page reloads instead (ADR-0055
keeps those hand edits worth protecting).

The lock is process-wide per path, because one ``ui`` process serves one
workspace and its saves are what need serialising. Another process writing
the file (``setup``, an editor) is caught by the hash, except in the
milliseconds between this read and its replace, which no file lock on Windows
would close for an editor that ignores it.

This module decides nothing about a file's contents: the caller's ``change``
validates and edits bytes, and returning them unchanged writes nothing.

An optional file (``settings.yaml``: Admin plan, *Settings*, "missing files
keep defaults") is read with ``absent_ok``: it reads as no bytes at
:data:`ABSENT_REVISION`, and a save against that revision creates it. Absent
is not the empty file's hash, so a file that appears meanwhile, even an empty
one, is an external edit like any other.
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
    "RevisionConflict",
    "Revised",
    "content_revision",
    "read_revisioned",
    "replace_if_unchanged",
]


class RevisionConflict(UserFacingError, RuntimeError):
    """The file changed since the revision a save was made against."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path.name} changed on disk since it was loaded; reload it first")
        self.path = path


@dataclass(frozen=True)
class Revised:
    revision: str
    """The file's revision after the save, which the next save must name."""
    written: bool
    """Whether the file was replaced: an unchanged result is not."""


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
    """The file's bytes and their revision, read under the save lock so a read
    never pairs one save's bytes with another's hash."""
    with _lock_for(path):
        return _read(path, absent_ok=absent_ok)


def replace_if_unchanged(
    path: Path,
    expected_revision: str,
    change: Callable[[bytes], bytes],
    *,
    absent_ok: bool = False,
) -> Revised:
    """Apply ``change`` to the file if it is still at ``expected_revision``.

    ``change`` runs inside the lock and may raise to refuse; nothing is written
    then. A result identical to the current bytes leaves the file untouched,
    and an absent file absent.
    """
    with _lock_for(path):
        current, revision = _read(path, absent_ok=absent_ok)
        if revision != expected_revision:
            raise RevisionConflict(path)
        edited = change(current)
        if edited == current:
            return Revised(expected_revision, written=False)
        write_bytes_atomic(path, edited)
        return Revised(content_revision(edited), written=True)


def _read(path: Path, *, absent_ok: bool) -> tuple[bytes, str]:
    try:
        data = read_bytes_retrying(path)
    except FileNotFoundError:
        if not absent_ok:
            raise
        return b"", ABSENT_REVISION
    return data, content_revision(data)

"""Delete a tree this project owns, whatever the filesystem says about it."""

from __future__ import annotations

import shutil
import stat
from collections.abc import Callable
from pathlib import Path


def _add_owner_write(path: Path) -> None:
    """On Windows this is what clears ``FILE_ATTRIBUTE_READONLY``."""
    path.chmod(path.stat().st_mode | stat.S_IWRITE)


def remove_tree(path: Path) -> None:
    """`shutil.rmtree` through read-only flags (Google Drive sets one on every
    directory it syncs). Windows refuses `os.rmdir` on a read-only directory,
    so the path is made writable; POSIX refuses to unlink an entry of a
    read-only parent, so the parent is too, but only inside the tree."""
    root = Path(path)

    def make_writable(func: Callable[[str], object], failed: str, exc: BaseException) -> None:
        if not isinstance(exc, PermissionError):
            raise exc
        target = Path(failed)
        _add_owner_write(target)
        parent = target.parent
        if parent == root or root in parent.parents:
            _add_owner_write(parent)
        func(failed)

    shutil.rmtree(root, onexc=make_writable)

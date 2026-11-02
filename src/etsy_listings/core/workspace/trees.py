"""Delete a tree this project owns, whatever the filesystem says about it.

Below :mod:`~etsy_listings.core.workspace.workspace` and
:mod:`~etsy_listings.core.workspace.calibration`, which both delete trees, so
neither has to import the other to do it.
"""

from __future__ import annotations

import shutil
import stat
from collections.abc import Callable
from pathlib import Path


def _add_owner_write(path: Path) -> None:
    """Add the owner-write bit, leaving the rest of the mode alone. On Windows
    this is what clears ``FILE_ATTRIBUTE_READONLY``."""
    path.chmod(path.stat().st_mode | stat.S_IWRITE)


def remove_tree(path: Path) -> None:
    """`shutil.rmtree`, surviving a tree that is marked read-only.

    Every tree this project deletes is one it created and owns -- a listing's
    directory, its render cache, its previews -- so a read-only flag on one is
    an artefact of the filesystem it sits on, never an instruction from the
    user. A workspace kept inside a Google Drive folder is the case that found
    this: Drive sets the flag on every directory it syncs.

    The two platforms this project is tested on refuse at different steps,
    and the hook has to answer both:

    * **Windows** refuses `os.rmdir` on a directory that is itself read-only.
      The files inside delete fine, so the traceback points at the one step
      that looks least likely to be the problem. Fix: make *the path* writable.
    * **POSIX** refuses to unlink an entry whose *parent directory* is not
      writable; the entry's own mode is irrelevant. Fix: make *the parent*
      writable. The first version of this hook only did the Windows half,
      said in its docstring that it did both, and passed on Windows while
      failing on the Ubuntu CI runner.

    Both are done, because it is not worth sniffing the platform to skip a
    chmod that is harmless where it is not needed. The parent is only touched
    while it is still inside the tree being removed: the root's own parent
    belongs to the caller, and write permission on it is not this function's
    to grant. Anything that is not a `PermissionError`, and any retry that
    fails again, is raised -- this widens exactly one refusal, not every one.
    """
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

"""The process's locks for things the workspace keys by name: listings,
mockup templates and listing templates.

A writer that reads, changes and writes one of them holds its lock around the
whole sequence, so two writers cannot interleave and lose an update. Each
domain's owner wraps :func:`hold`: ``ListingDocuments.lock`` for listings,
``CalibrationStore.lock`` for mockup templates, and the listing-template
library and frozen capture for listing templates.

A lock is keyed by the resolved directory its name becomes, casefolded. So
every :class:`Workspace` over one root shares it, two roots never do, names
differing only in case share one (as Windows makes them one directory), and an
in-workspace symlink alias shares its target's. A name is checked by its
domain's layout accessor and its directory by :meth:`Workspace.resolve`, so a
name that is not one path segment, or whose directory escapes the workspace,
is refused before anything is taken. The locks are reentrant: an operation
holding one may call another that takes it. Several names, such as a rename's
old and new, are taken in sorted order, so two callers naming the same pair in
opposite orders cannot each hold one and wait for the other.

Each lock is made on first use and kept for the life of the process, a few
hundred bytes per name ever touched. They do not cover a second process, such
as the CLI running beside the UI server, which nothing in the tool has ever
guarded.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from etsy_listings.core.workspace.workspace import Workspace

LockDomain = Literal["listing", "mockup-template", "listing-template"]

_DIRECTORIES: dict[LockDomain, Callable[[Workspace, str], Path]] = {
    "listing": lambda workspace, name: workspace.listing_dir(name),
    "mockup-template": lambda workspace, name: workspace.template_dir(name),
    "listing-template": lambda workspace, name: workspace.listing_template_dir(name),
}

_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


@contextmanager
def hold(workspace: Workspace, domain: LockDomain, name: str, *more: str) -> Iterator[None]:
    """Hold ``domain``'s lock for ``name``, and for each of ``more``, during
    the ``with`` block. Raises ``InvalidNameError`` or
    ``PathEscapesWorkspaceError`` before taking any of them."""
    keys = sorted({_key(workspace, domain, each) for each in (name, *more)})
    with ExitStack() as stack:
        for key in keys:
            with _GUARD:
                lock = _LOCKS.setdefault(key, threading.RLock())
            stack.enter_context(lock)
        yield


def _key(workspace: Workspace, domain: LockDomain, name: str) -> str:
    directory = _DIRECTORIES[domain](workspace, name)
    resolved = workspace.resolve(directory.relative_to(workspace.root).as_posix(), workspace.root)
    return str(resolved).casefold()

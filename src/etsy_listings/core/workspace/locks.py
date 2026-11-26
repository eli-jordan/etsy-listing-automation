"""The process's locks for things the workspace keys by name: listings, mockup
templates and listing templates.

A lock is keyed by the resolved, casefolded directory its name becomes, as
Windows makes case variants one directory, and no lock covers a second process
such as the CLI beside the UI server."""

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

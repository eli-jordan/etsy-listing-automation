"""Workspace-scoped foreground priority at CPU phase and solver boundaries."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Condition

from etsy_listings.core.workspace import Workspace

_CONDITION = Condition()
_FOREGROUND: dict[str, int] = {}


def _key(workspace: Workspace) -> str:
    return str(workspace.cache("preparation").resolve()).casefold()


@contextmanager
def interactive(workspace: Workspace) -> Iterator[None]:
    key = _key(workspace)
    with _CONDITION:
        _FOREGROUND[key] = _FOREGROUND.get(key, 0) + 1
    try:
        yield
    finally:
        with _CONDITION:
            remaining = _FOREGROUND[key] - 1
            if remaining:
                _FOREGROUND[key] = remaining
            else:
                del _FOREGROUND[key]
            _CONDITION.notify_all()


def yield_to_interactive(workspace: Workspace, check: Callable[[], None]) -> None:
    """Wait between work chunks, checking cancellation without holding our lock."""
    key = _key(workspace)
    while True:
        with _CONDITION:
            if not _FOREGROUND.get(key):
                return
            _CONDITION.wait(timeout=0.05)
        check()

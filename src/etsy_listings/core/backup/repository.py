from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.errors import UserFacingError


class ResticError(UserFacingError):
    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class RepositoryNotFoundError(ResticError):
    pass


class RepositoryLockedError(ResticError):
    pass


class WrongPasswordError(ResticError):
    pass


class ResticCancelledError(ResticError):
    pass


@dataclass(frozen=True)
class Snapshot:
    id: str
    short_id: str
    time: datetime
    paths: tuple[str, ...]
    hostname: str
    files: int | None = None
    """Files the backup read, from the snapshot's summary (restic 0.17+)."""
    size: int | None = None
    """Bytes the backup read, from the snapshot's summary."""
    tags: tuple[str, ...] = ()

    @property
    def workspace_id(self) -> str | None:
        for tag in self.tags:
            if tag.startswith(WORKSPACE_TAG):
                return tag.removeprefix(WORKSPACE_TAG)
        return None


WORKSPACE_TAG = "workspace:"
"""Every backup the app makes is tagged ``workspace:<workspace ID>``."""


def workspace_tag(workspace_id: str) -> str:
    return f"{WORKSPACE_TAG}{workspace_id}"


@dataclass(frozen=True)
class BackupFigures:
    files_done: int
    files_total: int | None = None


BackupListener = Callable[[BackupFigures], None]


@dataclass(frozen=True)
class BackupSummary:
    snapshot_id: str | None
    data_added: int | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreProgress:
    percent: float = 0.0
    """0 to 1."""
    bytes_done: int | None = None
    bytes_total: int | None = None
    files_done: int | None = None
    files_total: int | None = None
    seconds_left: int | None = None
    """Estimated from the rate so far; None until there is one."""


@dataclass(frozen=True)
class RepositoryCheck:
    ok: bool
    message: str | None = None


class Repository(Protocol):
    @property
    def path(self) -> Path: ...

    def init(self) -> str: ...

    def snapshots(self, *, lock: bool = True) -> tuple[Snapshot, ...]: ...

    def back_up(
        self,
        folder: Path,
        *,
        workspace_id: str,
        excludes: Sequence[str] = (),
        progress: BackupListener | None = None,
        cancel: threading.Event | None = None,
    ) -> BackupSummary: ...

    def forget(
        self,
        retention: RetentionSettings,
        *,
        workspace_id: str,
        cancel: threading.Event | None = None,
    ) -> None: ...

    def prune(self, *, cancel: threading.Event | None = None) -> None: ...

    def check(self, *, cancel: threading.Event | None = None) -> RepositoryCheck: ...

    def restore(
        self,
        snapshot: Snapshot,
        target: Path,
        *,
        progress: Callable[[RestoreProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RestoreProgress: ...

    def verify_password(self) -> None: ...


OpenRepository = Callable[[Path, Path, str], Repository]
"""``(binary, folder, password)``: the repository in ``folder``, run with the
restic at ``binary``. ``Restic`` is the real one; tests pass an in-memory one."""

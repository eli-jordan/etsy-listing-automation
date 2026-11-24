"""A restic repository's operations, in the backup's own terms
(workspace-backup spec, *Backup run*, *Restore* and *Missing repository*).

:class:`Repository` is the seam between the backup's application modules and
restic. Callers ask for an operation (back up a folder, forget by the
retention, prune, check, restore a snapshot, verify the password) and get
domain values back: progress figures while it runs, then a summary or a
check result. Which subcommands and flags that takes, restic's exit codes
and the shapes of its ``--json`` lines stay inside the adapter.

Two adapters satisfy it. ``core/backup/restic.py``'s ``Restic`` runs restic
itself and is reached only through ``core/application/backup_repository.py``
(Import Linter enforces it). ``tests/support/restic.py`` keeps a repository
in memory for behaviour tests.

The errors are restic's outcomes as the backup sees them; their message is
restic's own.
"""

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
    """A restic command failed; the message is restic's own."""

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class RepositoryNotFoundError(ResticError):
    """The repository folder is missing or is not a restic repository."""


class RepositoryLockedError(ResticError):
    """Another restic holds a lock that this operation cannot share."""


class WrongPasswordError(ResticError):
    """No key in the repository opens with the password."""


class ResticCancelledError(ResticError):
    """The operation was stopped before it finished, or before it started."""


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
        """The workspace ID its ``workspace:<id>`` tag names; None for an
        untagged snapshot, such as one made by hand (ADR-0060)."""
        for tag in self.tags:
            if tag.startswith(WORKSPACE_TAG):
                return tag.removeprefix(WORKSPACE_TAG)
        return None


WORKSPACE_TAG = "workspace:"
"""Every backup the app makes is tagged ``workspace:<workspace ID>``."""


def workspace_tag(workspace_id: str) -> str:
    """The tag every snapshot of the workspace ``workspace_id`` carries."""
    return f"{WORKSPACE_TAG}{workspace_id}"


@dataclass(frozen=True)
class BackupFigures:
    """How far a backup has read."""

    files_done: int
    files_total: int | None = None


BackupListener = Callable[[BackupFigures], None]


@dataclass(frozen=True)
class BackupSummary:
    """A finished backup. ``warnings`` name the files it could not read:
    the snapshot was made without them, and the backup still counts."""

    snapshot_id: str | None
    data_added: int | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreProgress:
    """How far a restore has got; the last one a restore reports is whole."""

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
    """``check``'s verdict: whether the repository's structure is sound,
    with restic's message when it is not or could not be checked."""

    ok: bool
    message: str | None = None


class Repository(Protocol):
    """One restic repository, opened with its password.

    Every operation that takes ``cancel`` checks it before it starts and
    raises :class:`ResticCancelledError` when it was set, then or part way.
    """

    @property
    def path(self) -> Path:
        """The repository's folder."""
        ...

    def init(self) -> str:
        """Create the repository in its empty folder; its id."""
        ...

    def snapshots(self, *, lock: bool = True) -> tuple[Snapshot, ...]:
        """Every snapshot, oldest first. ``lock=False`` reads without the
        shared lock, for a status that must answer while a backup runs."""
        ...

    def back_up(
        self,
        folder: Path,
        *,
        workspace_id: str,
        excludes: Sequence[str] = (),
        progress: BackupListener | None = None,
        cancel: threading.Event | None = None,
    ) -> BackupSummary:
        """Snapshot ``folder``, leaving out what matches ``excludes``,
        marked as the workspace ``workspace_id``'s."""
        ...

    def forget(
        self,
        retention: RetentionSettings,
        *,
        workspace_id: str,
        cancel: threading.Event | None = None,
    ) -> None:
        """Forget the workspace ``workspace_id``'s snapshots ``retention``
        does not keep, as one schedule whatever host or folder made them
        (spec, *Backup run* step 5). Other snapshots are left alone; their
        data stays until a prune."""
        ...

    def prune(self, *, cancel: threading.Event | None = None) -> None:
        """Delete the data no snapshot needs any more."""
        ...

    def check(self, *, cancel: threading.Event | None = None) -> RepositoryCheck:
        """Check the repository's structure. Any failure but a cancel is a
        failed check."""
        ...

    def restore(
        self,
        snapshot: Snapshot,
        target: Path,
        *,
        progress: Callable[[RestoreProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RestoreProgress:
        """Write ``snapshot`` into ``target`` without overwriting anything
        there; its last figures. A snapshot of one folder restores that
        folder's contents. A stop leaves the files restored so far."""
        ...

    def verify_password(self) -> None:
        """Raise :class:`WrongPasswordError` unless the password opens the
        repository."""
        ...


OpenRepository = Callable[[Path, Path, str], Repository]
"""``(binary, folder, password)``: the repository in ``folder``, run with the
restic at ``binary``. ``Restic`` is the real one; tests pass an in-memory one."""

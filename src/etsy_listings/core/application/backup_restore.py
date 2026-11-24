"""Restore one snapshot into a new folder (workspace-backup spec, *Restore*;
plan, PR 7): the whole sequence, for the server's coordinator and the CLI's
``backup restore`` alike.

:func:`prepare_restore` resolves the configured backup once, checks the
target, opens the repository and finds the snapshot, refusing before restic
writes anything. The :class:`PreparedRestore` it returns runs the restore,
checking the target once more just before restic starts, against
``settings.yaml`` read afresh: a Setup save, or a file landing in the
target, between the two is refused. The coordinator decides when a prepared
restore runs (its thread, the maintenance reservation, shutdown); the CLI
runs it at once.

The snapshot's own folder is restored, not the whole tree restic keeps, so
the target holds the workspace itself and ``ETSY_LISTINGS_ROOT`` can point
at it straight away.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.application.backup_repository import ConfiguredBackup, configured_backup
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.repository import (
    OpenRepository,
    Repository,
    ResticCancelledError,
    RestoreProgress,
    Snapshot,
)
from etsy_listings.core.errors import MissingError
from etsy_listings.core.workspace.workspace import Workspace

RestoreOutcome = Literal["running", "succeeded", "failed", "stopped"]


class RestoreStatus(BaseModel):
    """A restore, for the dialog and the status panel's strip."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    snapshot_time: datetime
    target: str
    started_at: datetime
    finished_at: datetime | None = None
    outcome: RestoreOutcome = "running"
    percent: float = 0.0
    """0 to 1."""
    bytes_done: int | None = None
    bytes_total: int | None = None
    files_done: int | None = None
    files_total: int | None = None
    seconds_left: int | None = None
    """Estimated from the rate so far; None until there is one."""
    message: str | None = None
    """Why it failed or stopped."""


@dataclass(frozen=True)
class PreparedRestore:
    """A restore whose target, repository and snapshot have been checked,
    ready to run. Built by :func:`prepare_restore`."""

    snapshot: Snapshot
    target: Path
    """Resolved and, when prepared, new or empty."""
    _workspace: Workspace
    _backup: ConfiguredBackup
    _repository: Repository

    def run(
        self,
        *,
        progress: Callable[[RestoreProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RestoreProgress:
        """Check the target again, then restore into it; its last figures.

        The re-check reads ``settings.yaml`` now, so a storage folder or
        destination saved since preparing is refused as a destination, and
        a target that has gained files is refused. restic then writes
        without overwriting, so files that land after this check stay.
        Raises the refusal, restic's error, or
        :class:`~etsy_listings.core.backup.repository.ResticCancelledError`
        when stopped, leaving the files restored so far."""
        if cancel is not None and cancel.is_set():
            raise ResticCancelledError("The restore was stopped.")
        settings = self._workspace.settings_if_readable(
            skipping="re-checking the restore target against the current backup settings"
        )
        target = self._backup.check_restore_target(
            self.target, now=None if settings is None else settings.backup
        )
        return self._repository.restore(self.snapshot, target, progress=progress, cancel=cancel)


def prepare_restore(
    workspace: Workspace,
    snapshot: str,
    target: Path,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> PreparedRestore:
    """Ready a restore of ``snapshot`` (an id, its start, or ``latest``) into
    the new folder ``target``. Refuses a target the restore would damage or
    mix files into (``ConfiguredBackup.check_restore_target``) before
    opening the repository, and a snapshot no id or more than one starts
    with as :class:`~etsy_listings.core.errors.MissingError`. Snapshots are
    listed without restic's lock, so a backup underway does not hold it up."""
    backup = configured_backup(workspace, binaries=binaries, restic=restic)
    checked = backup.check_restore_target(target)
    repository = backup.open()
    found = find_snapshot(repository.snapshots(lock=False), snapshot)
    return PreparedRestore(found, checked, workspace, backup, repository)


def find_snapshot(snapshots: Sequence[Snapshot], ref: str) -> Snapshot:
    """``latest``, or the snapshot whose id starts with ``ref``."""
    if ref == "latest" and snapshots:
        return snapshots[-1]
    found = [s for s in snapshots if ref and s.id.startswith(ref)]
    if len(found) != 1:
        raise MissingError(f"No backup has the id {ref}." if not found else f"{ref} is ambiguous.")
    return found[0]

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

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)

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
    """Estimated from the rate so far; ``None`` until there is one."""
    message: str | None = None
    """Why it failed or stopped."""


def default_target(workspace: Path, snapshot: Snapshot) -> Path:
    """The restore dialog's suggestion: a new sibling of the workspace,
    outside every folder a restore refuses."""
    return workspace.with_name(f"{workspace.name}-restore-{snapshot.short_id}")


@dataclass(frozen=True)
class PreparedRestore:
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
    backup = configured_backup(workspace, binaries=binaries, restic=restic)
    checked = backup.check_restore_target(target)
    repository = backup.open()
    found = find_snapshot(repository.snapshots(lock=False), snapshot)
    return PreparedRestore(found, checked, workspace, backup, repository)


def find_snapshot(snapshots: Sequence[Snapshot], ref: str) -> Snapshot:
    if ref == "latest" and snapshots:
        return snapshots[-1]
    found = [s for s in snapshots if ref and s.id.startswith(ref)]
    if len(found) != 1:
        raise MissingError(f"No backup has the id {ref}." if not found else f"{ref} is ambiguous.")
    return found[0]

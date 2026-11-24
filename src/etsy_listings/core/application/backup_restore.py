"""Restore one snapshot into a new folder (workspace-backup spec, *Restore*;
plan, PR 7). The server's coordinator runs it as a job and the CLI's
``backup restore`` runs it in the foreground; both refuse the same targets,
through ``ConfiguredBackup.check_restore_target`` in ``backup_repository``.

The snapshot's own folder is restored, not the whole tree restic keeps, so
the target holds the workspace itself and ``ETSY_LISTINGS_ROOT`` can point
at it straight away.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.backup.repository import Repository, RestoreProgress, Snapshot
from etsy_listings.core.errors import ConflictError, MissingError

RestoreOutcome = Literal["running", "succeeded", "failed", "stopped"]

LIVE_WORKSPACE = "That's your live workspace. Choose a new, empty folder."
"""The restore dialog's words (interactions, *Restore*)."""


class RestoreRefusedError(ConflictError):
    """A target the restore would damage or mix files into."""


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


def find_snapshot(snapshots: Sequence[Snapshot], ref: str) -> Snapshot:
    """``latest``, or the snapshot whose id starts with ``ref``."""
    if ref == "latest" and snapshots:
        return snapshots[-1]
    found = [s for s in snapshots if ref and s.id.startswith(ref)]
    if len(found) != 1:
        raise MissingError(f"No backup has the id {ref}." if not found else f"{ref} is ambiguous.")
    return found[0]


def restore(
    repository: Repository,
    snapshot: Snapshot,
    target: Path,
    *,
    progress: Callable[[RestoreProgress], None],
    cancel: threading.Event | None = None,
) -> RestoreProgress:
    """Run the restore; its last figures. The repository writes into
    ``target`` without overwriting anything there, so files that reached it
    after the target was checked stay. Raises restic's error, or
    :class:`~etsy_listings.core.backup.repository.ResticCancelledError` when
    stopped, leaving the files restored so far."""
    return repository.restore(snapshot, target, progress=progress, cancel=cancel)

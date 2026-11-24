"""Restore one snapshot into a new folder (workspace-backup spec, *Restore*;
plan, PR 7). The server's coordinator runs it as a job and the CLI's
``backup restore`` runs it in the foreground; both refuse the same targets.

The snapshot's own folder is restored, not the whole tree restic keeps, so
the target holds the workspace itself and ``ETSY_LISTINGS_ROOT`` can point
at it straight away.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.backup.repository import Repository, RestoreProgress, Snapshot
from etsy_listings.core.errors import ConflictError, MissingError, RefusedError

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


def check_target(
    target: Path, *, workspace: Path, repository: Path | None, destinations: Sequence[Path] = ()
) -> Path:
    """Refuse the live workspace, a folder inside it or the repository, and
    a folder that already holds files (spec, *Restore*)."""
    if not target.is_absolute():
        raise RefusedError(f"{target} is not a full path. Name the folder from its drive.")
    target = target.resolve()
    if _same(target, workspace):
        raise RestoreRefusedError(LIVE_WORKSPACE)
    if _within(target, workspace):
        raise RestoreRefusedError(
            f"{target} is inside your live workspace. Choose a new, empty folder outside it."
        )
    if repository is not None and _within(target, repository):
        raise RestoreRefusedError(f"{target} is in the backup storage folder. Choose another.")
    if any(_within(target, destination) for destination in destinations):
        raise RestoreRefusedError(f"{target} is in a backup destination. Choose another folder.")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise RestoreRefusedError(
            f"{target} already holds files. Choose a new, empty folder, or delete what a "
            "stopped restore left there."
        )
    return target


def _key(path: Path) -> str:
    return os.path.normcase(path.resolve())


def _same(a: Path, b: Path) -> bool:
    return _key(a) == _key(b)


def _within(path: Path, folder: Path) -> bool:
    inner, outer = _key(path), _key(folder)
    return inner == outer or inner.startswith(outer.rstrip(os.sep) + os.sep)


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
    after :func:`check_target` stay. Raises restic's error, or
    :class:`~etsy_listings.core.backup.repository.ResticCancelledError` when
    stopped, leaving the files restored so far."""
    return repository.restore(snapshot, target, progress=progress, cancel=cancel)

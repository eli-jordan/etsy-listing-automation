"""Restore one snapshot into a new folder (workspace-backup spec, *Restore*;
plan, PR 7). The server's coordinator runs it as a job and the CLI's
``backup restore`` runs it in the foreground; both refuse the same targets.

The snapshot's own folder is restored, not the whole tree restic keeps, so
the target holds the workspace itself and ``ETSY_LISTINGS_ROOT`` can point
at it straight away.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.backup.restic import Restic, Snapshot
from etsy_listings.core.errors import ConflictError, MissingError, RefusedError

RestoreOutcome = Literal["running", "succeeded", "failed", "stopped"]

LIVE_WORKSPACE = "That's your live workspace. Choose a new, empty folder."
"""The restore dialog's words (interactions, *Restore*)."""

RETRY_LOCK = "1h"
"""A restore started while a weekly prune holds restic's exclusive lock
waits for it rather than failing. An hour is more than any prune here."""


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
    """0 to 1, restic's ``percent_done``."""
    bytes_done: int | None = None
    bytes_total: int | None = None
    files_done: int | None = None
    files_total: int | None = None
    seconds_left: int | None = None
    """Estimated from the rate so far; None until restic reports progress."""
    message: str | None = None
    """Why it failed or stopped."""


def check_target(target: Path, *, workspace: Path, repository: Path | None) -> None:
    """Refuse the live workspace, a folder inside it or the repository, and
    a folder that already holds files (spec, *Restore*)."""
    if not target.is_absolute():
        raise RefusedError(f"{target} is not a full path. Name the folder from its drive.")
    if _within(target, workspace):
        raise RestoreRefusedError(
            LIVE_WORKSPACE
            if _same(target, workspace)
            else f"{target} is inside your live workspace. Choose a new, empty folder outside it."
        )
    if repository is not None and _within(target, repository):
        raise RestoreRefusedError(f"{target} is in the backup storage folder. Choose another.")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise RestoreRefusedError(
            f"{target} already holds files. Choose a new, empty folder, or delete what a "
            "stopped restore left there."
        )


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


_DRIVE = re.compile(r"^([A-Za-z]):[\\/]?(.*)$")


def tree_path(path: str) -> str:
    """Where restic keeps a backed-up folder inside the snapshot: ``C:\\x``
    becomes ``/C/x`` on Windows; a POSIX path stays as it is."""
    drive = _DRIVE.match(path)
    if drive is None:
        return path
    return f"/{drive.group(1)}/{drive.group(2)}".replace("\\", "/").rstrip("/")


def restore_arguments(snapshot: Snapshot, target: Path) -> tuple[str, ...]:
    """A snapshot of one folder restores that folder's contents; one made by
    hand of several folders restores them all as restic lays them out."""
    ref = (
        snapshot.id if len(snapshot.paths) != 1 else f"{snapshot.id}:{tree_path(snapshot.paths[0])}"
    )
    return ("restore", ref, "--target", str(target), "--retry-lock", RETRY_LOCK)


@dataclass
class RestoreProgress:
    """Figures from ``restic restore --json`` lines."""

    percent: float = 0.0
    bytes_done: int | None = None
    bytes_total: int | None = None
    files_done: int | None = None
    files_total: int | None = None
    seconds_left: int | None = None

    def hear(self, line: object) -> bool:
        """Take one line; whether it changed the figures."""
        if not isinstance(line, dict) or line.get("message_type") not in ("status", "summary"):
            return False
        summary = line["message_type"] == "summary"
        self.percent = 1.0 if summary else float(line.get("percent_done", self.percent))
        self.bytes_done = line.get("bytes_restored", self.bytes_done)
        self.bytes_total = line.get("total_bytes", self.bytes_total)
        self.files_done = line.get("files_restored", self.files_done)
        self.files_total = line.get("total_files", self.files_total)
        self.seconds_left = 0 if summary else _seconds_left(line, self.percent)
        return True


def _seconds_left(line: dict[str, object], percent: float) -> int | None:
    elapsed = line.get("seconds_elapsed")
    if not isinstance(elapsed, int | float) or percent <= 0:
        return None
    return round(elapsed * (1 - percent) / percent)


def restore(
    restic: Restic,
    snapshot: Snapshot,
    target: Path,
    *,
    progress: Callable[[RestoreProgress], None],
    cancel: threading.Event | None = None,
) -> RestoreProgress:
    """Run the restore; its last figures. Raises restic's error, or
    :class:`~etsy_listings.core.backup.restic.ResticCancelledError` when
    stopped, leaving the files restored so far."""
    figures = RestoreProgress()
    for line in restic.stream(*restore_arguments(snapshot, target), cancel=cancel):
        if figures.hear(line):
            progress(figures)
    return figures

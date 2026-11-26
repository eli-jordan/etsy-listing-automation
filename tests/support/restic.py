"""An in-memory restic repository for behaviour tests (workspace-backup plan,
P3): the second adapter at ``core/backup/repository.py``'s seam.

Pass an :class:`InMemoryRestic` wherever the application takes ``restic=``
(``BackupRunner``, ``BackupEnvironment``, ``create_repository``...). Every
repository it opens shares its snapshots, so a scheduler, a restore and a
status read see one repository, as they would on disk. Tests script it in
the backup's own terms: a failing operation, one held until released or
stopped, a backup with warnings, a password the repository was made with.
How restic spells any of that is ``tests/core/unit/test_restic_runner.py``'s.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from etsy_listings.core.backup.repository import (
    BackupFigures,
    BackupSummary,
    Repository,
    RepositoryCheck,
    ResticCancelledError,
    ResticError,
    RestoreProgress,
    Snapshot,
    WrongPasswordError,
    workspace_tag,
)
from etsy_listings.core.config.settings import RetentionSettings

HOLD_LIMIT_SECONDS = 30.0
"""A held operation that nobody releases or stops goes on after this, so a
broken test fails instead of hanging."""

QUARTER_RESTORED = RestoreProgress(
    fraction=0.25,
    bytes_done=2_000_000,
    bytes_total=8_000_000,
    files_done=100,
    files_total=400,
    seconds_left=180,
)
WHOLE_RESTORE = RestoreProgress(
    fraction=1.0,
    bytes_done=8_000_000,
    bytes_total=8_000_000,
    files_done=400,
    files_total=400,
    seconds_left=0,
)


def snapshot_id(number: int) -> str:
    """The id of the ``number``-th snapshot, counting from 1."""
    return f"{number:064x}"


@dataclass(frozen=True)
class MemorySnapshot:
    """A snapshot as the in-memory repository keeps it. A bare ``datetime``
    in :attr:`InMemoryRestic.snapshots` is one made by hand: untagged, on
    ``pc``."""

    time: datetime
    workspace_id: str | None = None
    hostname: str = "pc"
    path: str = "/workspace"
    number: int | None = None
    """Its id's number; None numbers it by its place in the list."""


def kept_by_retention(times: Iterable[datetime], retention: RetentionSettings) -> set[datetime]:
    """What restic's ``forget`` keeps of one group: every snapshot within
    ``keep_within_days`` of the newest, and the newest of each of the last
    ``weekly + 1`` weeks and ``monthly + 1`` months that have one (spec,
    *Backup run* step 5). As restic 0.17 and later do, a rule with fewer
    weeks or months than it may keep also keeps the oldest snapshot."""
    times = list(times)
    if not times:
        return set()
    latest = max(times)
    kept = {t for t in times if latest - t < timedelta(days=retention.keep_within_days)}
    kept |= _newest_of_each(times, lambda t: t.isocalendar()[:2], retention.weekly + 1)
    kept |= _newest_of_each(times, lambda t: (t.year, t.month), retention.monthly + 1)
    return kept


def _newest_of_each(
    times: list[datetime], period: Callable[[datetime], tuple[int, int]], count: int
) -> set[datetime]:
    """The newest time in each of the ``count`` latest periods, and the
    oldest time when there are fewer periods than ``count``."""
    latest: dict[tuple[int, int], datetime] = {}
    for t in times:
        key = period(t)
        latest[key] = max(latest.get(key, t), t)
    kept = {latest[key] for key in sorted(latest, reverse=True)[:count]}
    if len(latest) < count:
        kept.add(min(times))
    return kept


class InMemoryRestic:
    """Opens repositories that live in memory; ``now`` dates each backup.

    Operations are named as the interface names them: ``init``,
    ``snapshots``, ``back_up``, ``forget``, ``prune``, ``check``,
    ``restore`` and ``verify_password``.
    """

    def __init__(self, now: Callable[[], datetime]) -> None:
        self.now = now
        self.snapshots: list[datetime | MemorySnapshot] = []
        """Each snapshot, oldest first: a bare time is one made by hand."""
        self.hostname = "pc"
        """The host the next backups are made on."""
        self.password: str | None = None
        """When set, opening with any other password fails as restic does."""
        self.backup_figures: Sequence[BackupFigures] = (BackupFigures(5, 10),)
        self.warnings: tuple[str, ...] = ()
        """Files the next backups could not read; they still complete."""
        self.data_added: int | None = None
        self.restore_figures: Sequence[RestoreProgress] = (QUARTER_RESTORED, WHOLE_RESTORE)
        """A held restore reports all but the last before it waits."""
        self.on_start: Callable[[str], None] | None = None
        """Told each operation's name as it starts."""
        self.operations: list[str] = []
        self.reads_without_lock = 0
        self._failing: dict[str, ResticError] = {}
        self._holds: dict[str, threading.Event] = {}
        self._stopped: list[str] = []
        self._forgotten = 0
        """Snapshots forgotten so far, so a new one never reuses an id."""
        self._lock = threading.Lock()

    def __call__(self, binary: Path, folder: Path, password: str) -> Repository:
        return _Repository(self, folder, password)

    def fail(self, operation: str, error: ResticError) -> None:
        """Make ``operation`` fail with ``error``; a failed ``check`` returns
        it as a failed check, as the real adapter does."""
        self._failing[operation] = error

    def hold(self, operation: str) -> threading.Event:
        """Keep ``operation`` running once it has reported its first
        figures, until the returned event is set or it is stopped."""
        release = threading.Event()
        self._holds[operation] = release
        return release

    def ran(self, operation: str) -> int:
        with self._lock:
            return self.operations.count(operation)

    def stopped(self, operation: str) -> int:
        """How many of ``operation``'s runs were stopped part way."""
        with self._lock:
            return self._stopped.count(operation)

    # --------------------------------------------------- for _Repository

    def start(self, operation: str, password: str, cancel: threading.Event | None) -> None:
        if cancel is not None and cancel.is_set():
            raise ResticCancelledError(f"{operation} was stopped before it started")
        with self._lock:
            self.operations.append(operation)
        if self.on_start is not None:
            self.on_start(operation)
        if self.password is not None and password != self.password:
            raise WrongPasswordError("restic: Fatal: wrong password or no key found", exit_code=12)
        error = self._failing.get(operation)
        if error is not None:
            raise error

    def wait_if_held(self, operation: str, cancel: threading.Event | None) -> None:
        release = self._holds.get(operation)
        if release is None:
            return
        deadline = time.monotonic() + HOLD_LIMIT_SECONDS
        while not release.wait(0.01) and time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                with self._lock:
                    self._stopped.append(operation)
                raise ResticCancelledError(f"{operation} was stopped")

    def snapshot_list(self, *, lock: bool) -> tuple[Snapshot, ...]:
        with self._lock:
            self.reads_without_lock += not lock
            found = list(self.snapshots)
        return tuple(_listed(n, entry) for n, entry in enumerate(found, 1))

    def add_snapshot(self, workspace_id: str | None = None) -> str:
        with self._lock:
            number = len(self.snapshots) + 1 + self._forgotten
            self.snapshots.append(
                MemorySnapshot(self.now(), workspace_id, self.hostname, number=number)
            )
            return snapshot_id(number)

    def workspace_snapshots(self, workspace_id: str) -> list[MemorySnapshot]:
        """The snapshots tagged as the workspace ``workspace_id``'s."""
        with self._lock:
            return [
                entry
                for entry in self.snapshots
                if isinstance(entry, MemorySnapshot) and entry.workspace_id == workspace_id
            ]

    def forget_snapshots(self, retention: RetentionSettings, workspace_id: str) -> None:
        """Only ``workspace_id``'s, as one group whatever host or path."""
        group = self.workspace_snapshots(workspace_id)
        kept = kept_by_retention((entry.time for entry in group), retention)
        gone = [entry for entry in group if entry.time not in kept]
        with self._lock:
            for entry in gone:
                self.snapshots.remove(entry)
            self._forgotten += len(gone)


class _Repository:
    def __init__(self, restic: InMemoryRestic, folder: Path, password: str) -> None:
        self._restic = restic
        self._folder = folder
        self._password = password

    @property
    def path(self) -> Path:
        return self._folder

    def _start(self, operation: str, cancel: threading.Event | None = None) -> None:
        self._restic.start(operation, self._password, cancel)

    def init(self) -> str:
        """Writes restic's ``config`` into the folder opened, which may not
        be the configured one."""
        self._start("init")
        self._folder.mkdir(parents=True, exist_ok=True)
        (self._folder / "config").write_bytes(b"{}")
        return "f00d"

    def snapshots(self, *, lock: bool = True) -> tuple[Snapshot, ...]:
        self._start("snapshots")
        return self._restic.snapshot_list(lock=lock)

    def back_up(
        self,
        folder: Path,
        *,
        workspace_id: str,
        excludes: Sequence[str] = (),
        progress: Callable[[BackupFigures], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> BackupSummary:
        self._start("back_up", cancel)
        for figures in self._restic.backup_figures:
            if progress is not None:
                progress(figures)
        self._restic.wait_if_held("back_up", cancel)
        made = self._restic.add_snapshot(workspace_id)
        return BackupSummary(made, self._restic.data_added, self._restic.warnings)

    def forget(
        self,
        retention: RetentionSettings,
        *,
        workspace_id: str,
        cancel: threading.Event | None = None,
    ) -> None:
        self._start("forget", cancel)
        self._restic.wait_if_held("forget", cancel)
        self._restic.forget_snapshots(retention, workspace_id)

    def prune(self, *, cancel: threading.Event | None = None) -> None:
        self._start("prune", cancel)
        self._restic.wait_if_held("prune", cancel)

    def check(self, *, cancel: threading.Event | None = None) -> RepositoryCheck:
        try:
            self._start("check", cancel)
            self._restic.wait_if_held("check", cancel)
        except ResticCancelledError:
            raise
        except ResticError as exc:
            return RepositoryCheck(ok=False, message=str(exc))
        return RepositoryCheck(ok=True)

    def restore(
        self,
        snapshot: Snapshot,
        target: Path,
        *,
        progress: Callable[[RestoreProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> RestoreProgress:
        self._start("restore", cancel)
        *before, last = self._restic.restore_figures
        for figures in before:
            if progress is not None:
                progress(figures)
        self._restic.wait_if_held("restore", cancel)
        if progress is not None:
            progress(last)
        return last

    def verify_password(self) -> None:
        self._start("verify_password")


def _listed(number: int, entry: datetime | MemorySnapshot) -> Snapshot:
    if isinstance(entry, datetime):
        entry = MemorySnapshot(entry)
    identity = snapshot_id(entry.number or number)
    return Snapshot(
        id=identity,
        short_id=identity[:8],
        time=entry.time,
        paths=(entry.path,),
        hostname=entry.hostname,
        tags=() if entry.workspace_id is None else (workspace_tag(entry.workspace_id),),
    )

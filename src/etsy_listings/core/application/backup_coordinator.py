"""The server's backups: the schedule, Back up now, repair, and the status
(workspace-backup spec, *Scope and decisions*, Scheduling and Manual run;
plan, PR 5).

**One operation at a time.** A backup run and a repair both write to a
destination, so each takes the one slot :attr:`BackupCoordinator.running`
describes. A second is refused with :class:`BackupBusyError`; the
scheduler simply waits for its next check.

**A restore beside them.** A restore only reads the repository, under
restic's shared lock, so it has a slot of its own and backups keep running.
Forget, prune and check need the exclusive lock, so a backup during a
restore leaves them to a later run (spec, *Restore*).

**The schedule.** A backup is due ``interval_hours`` after the newest
snapshot restic lists, at once when there is none, and an hour after a run
that failed (``backup_overview.next_due``). The scheduler checks at start-up,
so an overdue backup runs straight away, then every :data:`CHECK_EVERY`
seconds, reading ``settings.yaml`` afresh each time, so a changed interval
counts from the next check. The clock is injected; no test sleeps for an
interval.

**No repository, no backup.** A repository folder without restic's
``config`` stops the schedule and is reported (spec, *Missing repository*):
nothing here creates one by itself. The seller creates a new one or
connects an existing one (``backup_missing``); a connect holds the slot
while it copies, so no backup or repair starts meanwhile.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from etsy_listings.core.application.backup_missing import (
    Replacement,
    connect_repository,
    create_new_repository,
    has_repository,
)
from etsy_listings.core.application.backup_overview import (
    BackupFacts,
    BackupOverview,
    HistoryEntry,
    RepositoryReading,
    RunningBackup,
    backup_overview,
    history,
    last_success,
    next_due,
)
from etsy_listings.core.application.backup_repository import (
    backup_settings,
    open_repository,
    stored_password,
)
from etsy_listings.core.application.backup_restore import (
    RestoreProgress,
    RestoreStatus,
    check_target,
    find_snapshot,
    restore,
)
from etsy_listings.core.application.backup_run import BackupProgress, BackupRunner
from etsy_listings.core.application.backup_setup import BackupSetUp, set_up_backups
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import RepairResult
from etsy_listings.core.backup.restic import Launch, Restic, ResticCancelledError, Snapshot
from etsy_listings.core.backup.state import BackupState, BackupStateStore, RunRecord
from etsy_listings.core.config.settings import BackupSettings
from etsy_listings.core.errors import ConflictError, MissingError, UserFacingError
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

CHECK_EVERY = 300.0
"""Seconds between the scheduler's checks: each reads the snapshots, so a
backup starts at most five minutes after it falls due."""


class BackupBusyError(ConflictError):
    def __init__(self, running: RunningBackup) -> None:
        super().__init__(f"A {running.operation} is already running; try again when it ends.")


class RestoreBusyError(ConflictError):
    def __init__(self) -> None:
        super().__init__("A restore is already running; stop it or wait for it to end.")


class RepositoryMissingError(ConflictError):
    def __init__(self, repository: Path) -> None:
        super().__init__(f"Backup repository not found at {repository}.")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class BackupEnvironment:
    """What a coordinator runs with, injected by tests: ``home`` keeps the
    state and history under ``tmp_path`` (plan, P2), ``launch`` replaces
    restic, ``now`` is the clock."""

    home: Path | None = None
    launch: Launch | None = None
    now: Callable[[], datetime] = _utc_now


class BackupCoordinator:
    def __init__(
        self,
        workspace: Workspace,
        *,
        gate: JobGate | None,
        environment: BackupEnvironment | None = None,
        check_every: float = CHECK_EVERY,
    ) -> None:
        self._workspace = workspace
        self._gate = gate
        self._env = environment or BackupEnvironment()
        self._binaries = ResticBinaries(home=self._env.home)
        self._store = BackupStateStore(self._env.home)
        self._check_every = check_every
        self._lock = threading.Lock()
        self._maintenance_lock = threading.Lock()
        self._running: RunningBackup | None = None
        self._reading: tuple[Path, datetime, RepositoryReading] | None = None
        """The last snapshot read, its repository and time, so a status poll
        does not start restic each time; refreshed by every check and
        operation, and once a run has finished since."""
        self._worker: threading.Thread | None = None
        self._scheduler: threading.Thread | None = None
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._cancel = threading.Event()
        self._restore: RestoreStatus | None = None
        """The latest restore since start-up, kept once it ends so the page
        can say where the files are."""
        self._restorer: threading.Thread | None = None
        self._stop_restore = threading.Event()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._scheduler = threading.Thread(target=self._schedule, name="backup-scheduler")
        self._scheduler.daemon = True
        self._scheduler.start()

    def stop(self) -> None:
        """Stop the schedule and any restic part way; the run is recorded
        as stopped. The gate's own stop ends a backup waiting for quiet."""
        with self._lock:
            # Under the lock, so no worker starts after this reads it.
            self._stopping.set()
            worker, restorer = self._worker, self._restorer
        self._cancel.set()
        self._stop_restore.set()
        self._wake.set()
        for thread in (self._scheduler, worker, restorer):
            if thread is not None:
                thread.join()

    def wake(self) -> None:
        """Check now, as after a Setup save."""
        self._wake.set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the backup in progress, if any."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def _schedule(self) -> None:
        while not self._stopping.is_set():
            try:
                self.check()
            except Exception:
                # A defect in one check must not end the schedule for good.
                logger.exception("backup scheduler check failed")
            self._wake.wait(self._check_every)
            self._wake.clear()

    # ----------------------------------------------------------- operations

    def check(self) -> bool:
        """Start a backup if one is due; whether it did."""
        settings = self._settings()
        if settings is None or self._stopping.is_set() or self.running is not None:
            return False
        reading = self._refresh(settings)
        if reading.missing:
            return False
        due = next_due(settings, last_success(reading), self._runs(settings), self._env.now())
        if self._env.now() < due:
            return False
        try:
            self._start_backup()
        except ConflictError:
            return False
        return True

    def run_now(self) -> None:
        """Back up now, whenever nothing else runs (spec, *Manual run*)."""
        settings = backup_settings(self._workspace)
        if self._refresh(settings).missing:
            raise RepositoryMissingError(settings.repository)
        self._start_backup()

    def set_up(self, answers: BackupSetUp, *, expected_revision: str) -> None:
        """Set backups up (``backup_setup``), then start the first backup."""
        if self._settings() is not None:
            raise ConflictError("Backups are already set up; change them on the Setup page.")
        self._prepare_first_backup(
            lambda: set_up_backups(
                self._workspace,
                answers,
                expected_revision=expected_revision,
                binaries=self._binaries,
                launch=self._env.launch,
            )
        )

    def create_repository(self, answers: Replacement) -> None:
        """Create a new repository where the missing one was named or the
        seller chose, then start the first backup into it."""
        self._prepare_first_backup(
            lambda: create_new_repository(
                self._workspace, answers, binaries=self._binaries, launch=self._env.launch
            )
        )

    def connect(self, source: Path, answers: Replacement) -> None:
        """Copy the repository at ``source`` to local disk and use it;
        answers once it is connected, holding the slot meanwhile. The
        schedule then backs up when the copied snapshots say it is due."""
        self._claim("connect", None)
        try:
            connect_repository(
                self._workspace,
                source,
                answers,
                binaries=self._binaries,
                launch=self._env.launch,
            )
        finally:
            self._release()
        self.wake()

    def repair(self, destination: Path) -> RepairResult:
        """Set aside what changed in ``destination`` and copy again, holding
        the slot so no backup copies there meanwhile."""
        self._claim("repair", destination)
        try:
            return self._runner().repair(destination)
        finally:
            self._release()

    @property
    def running(self) -> RunningBackup | None:
        with self._lock:
            return self._running

    def _claim(
        self, operation: Literal["backup", "repair", "connect"], destination: Path | None
    ) -> None:
        with self._lock:
            self._claim_locked(operation, destination)

    def _claim_locked(
        self, operation: Literal["backup", "repair", "connect"], destination: Path | None
    ) -> None:
        if self._stopping.is_set():
            raise ConflictError("The app is shutting down.")
        if self._running is not None:
            raise BackupBusyError(self._running)
        self._running = RunningBackup(
            operation=operation,
            started_at=self._env.now(),
            step="copying" if destination is not None or operation == "connect" else "starting",
            destination=None if destination is None else str(destination),
        )

    def _release(self) -> None:
        try:
            if not self._stopping.is_set() and (settings := self._settings()) is not None:
                self._refresh(settings)
        finally:
            with self._lock:
                self._running = None

    def _start_backup(self) -> None:
        """Run a backup on its own thread, or :class:`BackupBusyError`."""
        with self._lock:
            self._claim_locked("backup", None)
            try:
                self._launch_backup()
            except BaseException:
                self._running = None
                raise

    def _prepare_first_backup(self, prepare: Callable[[], object]) -> None:
        self._claim("backup", None)
        try:
            prepare()
            with self._lock:
                self._launch_backup()
        except BaseException:
            self._release()
            raise

    def _launch_backup(self) -> None:
        """Under the coordinator lock, hand the claimed slot to the worker."""
        if self._stopping.is_set():
            raise ConflictError("The app is shutting down.")
        worker = threading.Thread(target=self._back_up, name="backup-run", daemon=True)
        worker.start()
        self._worker = worker

    def _back_up(self) -> None:
        try:
            self._runner().run(
                gate=self._gate,
                progress=self._heard,
                cancel=self._cancel,
                maintenance=self._maintenance,
            )
        finally:
            self._release()

    def _heard(self, progress: BackupProgress) -> None:
        with self._lock:
            running = self._running
            if running is None:
                return
            waiting = progress.step == "waiting"
            since = (running.waiting_since or self._env.now()) if waiting else None
            self._running = running.model_copy(
                update={
                    "step": progress.step,
                    "waiting_for": progress.waiting_for if waiting else None,
                    "waiting_since": since,
                    "files_done": progress.files_done,
                    "files_total": progress.files_total,
                    "destination": progress.destination,
                }
            )

    # -------------------------------------------------------------- restore

    @property
    def restoring(self) -> bool:
        with self._lock:
            return self._restore is not None and self._restore.outcome == "running"

    @contextmanager
    def _maintenance(self) -> Iterator[bool]:
        """Reserve the exclusive commands or defer them to a later run."""
        acquired = self._maintenance_lock.acquire(blocking=False)
        try:
            yield acquired and not self.restoring
        finally:
            if acquired:
                self._maintenance_lock.release()

    def start_restore(self, snapshot: str, target: Path) -> None:
        """Restore ``snapshot`` (an id, its start, or ``latest``) into the
        new folder ``target`` on its own thread (spec, *Restore*)."""
        settings = backup_settings(self._workspace)
        target = check_target(
            target,
            workspace=self._workspace.root,
            repository=settings.repository,
            destinations=settings.destinations,
        )
        restic = open_repository(
            self._workspace, binaries=self._binaries, launch=self._env.launch, settings=settings
        )
        found = find_snapshot(restic.snapshots(lock=False), snapshot)
        with self._lock:
            if self._stopping.is_set():
                raise ConflictError("The app is shutting down.")
            if self._restore is not None and self._restore.outcome == "running":
                raise RestoreBusyError
            self._restore = RestoreStatus(
                snapshot_id=found.id,
                snapshot_time=found.time,
                target=str(target),
                started_at=self._env.now(),
            )
            self._stop_restore = stop = threading.Event()
            self._restorer = threading.Thread(
                target=self._run_restore,
                args=(restic, found, target, stop),
                name="backup-restore",
                daemon=True,
            )
            self._restorer.start()

    def stop_restore(self) -> None:
        """Stop the restore, answering once it has; the files restored so
        far stay in its folder."""
        with self._lock:
            self._stop_restore.set()
            restorer = self._restorer
        if restorer is not None:
            restorer.join()

    def join_restore(self, timeout: float | None = None) -> None:
        restorer = self._restorer
        if restorer is not None:
            restorer.join(timeout)

    def _run_restore(
        self, restic: Restic, snapshot: Snapshot, target: Path, stop: threading.Event
    ) -> None:
        update: dict[str, object] = {"outcome": "succeeded"}
        try:
            with self._maintenance_lock:
                self._restore_to(restic, snapshot, target, stop)
        except ResticCancelledError:
            update = {"outcome": "stopped", "message": "The restore was stopped."}
        except UserFacingError as exc:
            update = {"outcome": "failed", "message": str(exc)}
        except Exception:
            logger.exception("restore failed")
            update = {"outcome": "failed", "message": "The restore failed; see the server log."}
        with self._lock:
            if self._restore is not None:
                update["finished_at"] = self._env.now()
                self._restore = self._restore.model_copy(update=update)

    def _restore_to(
        self, restic: Restic, snapshot: Snapshot, target: Path, stop: threading.Event
    ) -> None:
        if stop.is_set():
            raise ResticCancelledError("The restore was stopped.")
        current = self._settings()
        protected = () if current is None else (current.repository, *current.destinations)
        target = check_target(
            target,
            workspace=self._workspace.root,
            repository=restic.repository,
            destinations=protected,
        )
        restore(restic, snapshot, target, progress=self._heard_restore, cancel=stop)

    def _heard_restore(self, figures: RestoreProgress) -> None:
        with self._lock:
            if self._restore is not None:
                self._restore = self._restore.model_copy(update=vars(figures))

    def _runner(self) -> BackupRunner:
        return BackupRunner(
            self._workspace,
            self._binaries,
            home=self._env.home,
            launch=self._env.launch,
            now=self._env.now,
        )

    # --------------------------------------------------------------- status

    def overview(self) -> BackupOverview:
        settings = self._settings()
        state = BackupState(repository="")
        runs: list[RunRecord] = []
        reading = RepositoryReading(missing=False)
        if settings is not None:
            state = self._store.load(settings.repository)
            runs = self._runs(settings)
            reading = self._cached(settings, runs)
        facts = BackupFacts(
            settings,
            state,
            runs,
            reading,
            self.running,
            self._env.now(),
            password_stored=settings is not None and stored_password(self._workspace) is not None,
        )
        with self._lock:
            restoring = self._restore
        return backup_overview(facts).model_copy(update={"restore": restoring})

    def snapshots(self) -> tuple[Snapshot, ...]:
        """Every snapshot restic lists, read afresh, oldest first."""
        reading = self._refresh(backup_settings(self._workspace))
        if reading.snapshots is None:
            raise MissingError(reading.problem or "The backups could not be read.")
        return reading.snapshots

    def history(self) -> list[HistoryEntry]:
        settings = self._settings()
        if settings is None:
            return []
        runs = self._runs(settings)
        snapshots = self._cached(settings, runs).snapshots or ()
        return history(runs, snapshots, settings.retention, self._env.now())

    def _settings(self) -> BackupSettings | None:
        settings = self._workspace.settings_if_readable(skipping="checking the backup schedule")
        return None if settings is None else settings.backup

    def _runs(self, settings: BackupSettings) -> list[RunRecord]:
        return [run for run in self._store.runs() if run.repository == str(settings.repository)]

    def _cached(self, settings: BackupSettings, runs: list[RunRecord]) -> RepositoryReading:
        """The last read, unless it was of another repository or a run has
        been recorded since: a run's history line lands before the run's
        own refresh, and its snapshot must be listed with it."""
        cached = self._reading
        newest = runs[-1].finished_at if runs else None
        fresh = cached is not None and (newest is None or newest < cached[1])
        if cached is not None and fresh and cached[0] == settings.repository:
            return cached[2]
        return self._refresh(settings)

    def _refresh(self, settings: BackupSettings) -> RepositoryReading:
        reading = self._read_repository(settings)
        self._reading = (settings.repository, self._env.now(), reading)
        return reading

    def _read_repository(self, settings: BackupSettings) -> RepositoryReading:
        if not has_repository(settings.repository):
            return RepositoryReading(missing=True)
        try:
            restic = open_repository(
                self._workspace,
                binaries=self._binaries,
                launch=self._env.launch,
                settings=settings,
            )
            return RepositoryReading(missing=False, snapshots=restic.snapshots(lock=False))
        except UserFacingError as exc:
            return RepositoryReading(missing=False, problem=str(exc))

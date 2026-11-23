"""One backup run: back up, forget, and the weekly prune and check
(workspace-backup spec, *Backup run*; plan, PR 3).

The server passes its :class:`JobGate`, so the run waits for quiet, pauses
the background jobs for the ``restic backup`` step alone and resumes them
whatever happened; the CLI passes none (spec, *CLI*). Each run, failed ones
included, is appended to the history in ``~/.etsy-listings``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from etsy_listings.core.application.backup_repository import backup_settings, open_repository
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.restic import Launch, Restic, ResticCancelledError, ResticError
from etsy_listings.core.backup.state import (
    BackupState,
    BackupStateStore,
    CheckResult,
    RunOutcome,
    RunRecord,
)
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.workspace import Workspace

Clock = Callable[[], datetime]
PARTIAL_SNAPSHOT_EXIT = 3
PRUNE_INTERVAL = timedelta(days=7)
"""Prune, then check, weekly (spec, *Backup run* step 6)."""
BackupStep = Literal["starting", "waiting", "backing_up", "forgetting", "pruning", "checking"]


@dataclass(frozen=True)
class BackupProgress:
    """Enough for the running line: the step, the job a backup waits for,
    and files read out of the total while backing up."""

    step: BackupStep
    waiting_for: str | None = None
    files_done: int | None = None
    files_total: int | None = None


Progress = Callable[[BackupProgress], None]

EXCLUDES: tuple[str, ...] = (
    # restic patterns: one without a leading "/" matches at any depth.
    # tests/core/behaviour/test_backup_excludes.py pins each to its writer.
    #
    # Every temp-then-rename writer that ends its names in .tmp: a dot, the
    # name and a random part from workspace/atomic.py, engine/stages/render.py
    # and preparation/scene_cache.py; the name and a uuid from market/cache.py
    # and market/snapshot.py; the name, pid and thread from ai/viewable.py;
    # the bare name from clients/etsy/tokens.py and engine/lock.py.
    "*.tmp",
    # The Marigold worker's predictions, ".{name}.npz.{uuid}" (server.py _publish).
    ".*.npz.*",
    # preparation/position_fits.py: a fit's ".{key}-{uuid}" staging directory.
    ".cache/position-fits/.*",
    # application/mockup_templates.py: a photo between its two renames.
    ".*.renaming.png",
    # batches/staging.py: an upload as it streams in, and a dropped ZIP while
    # its PNGs are read out.
    ".cache/staging/*/uploads/incoming.png",
    ".cache/staging/*/upload.zip",
    # preparation/artifacts.py: a map generation before it is published.
    "_renderer/maps/staging",
    # workspace/calibration.py: a calibration save's payloads and backups.
    "_renderer/calibration-transaction",
)
"""Temporary names the app's own writers use (spec, *Backup run* step 3)."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def forget_arguments(retention: RetentionSettings) -> tuple[str, ...]:
    """restic counts the current week and month as one of each, so N past
    weeks and months are N + 1 (spec, *Backup run* step 5)."""
    return (
        "forget",
        "--keep-within",
        f"{retention.keep_within_days}d",
        "--keep-weekly",
        str(retention.weekly + 1),
        "--keep-monthly",
        str(retention.monthly + 1),
    )


@dataclass(frozen=True)
class BackupRunner:
    """Runs against ``workspace``'s configured repository. ``home`` holds
    the state and history; tests pass one under ``tmp_path`` (plan, P2)."""

    workspace: Workspace
    binaries: ResticBinaries
    home: Path | None = None
    launch: Launch | None = None
    now: Clock = _utc_now

    def run(
        self,
        *,
        gate: JobGate | None = None,
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
    ) -> RunRecord:
        """Back up, forget, and prune and check when due. ``cancel`` stops
        restic part way; the run is then recorded as stopped."""
        settings = backup_settings(self.workspace)
        store = BackupStateStore(self.home)
        run = _Run(self.now(), str(settings.repository), progress or (lambda _: None))
        try:
            restic = open_repository(self.workspace, binaries=self.binaries, launch=self.launch)
            with _paused(gate, run):
                run.enter("backing_up")
                self._back_up(restic, run, cancel)
            run.enter("forgetting")
            restic.run(*forget_arguments(settings.retention), cancel=cancel)
            if self._prune_due(store.load(settings.repository)):
                run.enter("pruning")
                restic.run("prune", cancel=cancel)
                state = store.load(settings.repository)
                store.save(state.model_copy(update={"last_prune": self.now()}))
                run.enter("checking")
                run.failure = self._check(restic, store).message
        except (_StoppedError, ResticCancelledError) as exc:
            run.stopped, run.failure = True, str(exc)
        except UserFacingError as exc:
            run.failure = str(exc)
        record = run.record(self.now())
        store.append_run(record)
        return record

    def _back_up(self, restic: Restic, run: _Run, cancel: threading.Event | None) -> None:
        arguments = ["backup", str(self.workspace.root)]
        for pattern in EXCLUDES:
            arguments += ["--exclude", pattern]
        try:
            for line in restic.stream(*arguments, cancel=cancel):
                run.hear(line)
        except ResticError as exc:
            # 3: the snapshot was made, but some files could not be read.
            if exc.exit_code != PARTIAL_SNAPSHOT_EXIT or run.snapshot_id is None:
                raise

    def check(self) -> CheckResult:
        """``restic check`` of the local repository, recorded in the state."""
        restic = open_repository(self.workspace, binaries=self.binaries, launch=self.launch)
        return self._check(restic, BackupStateStore(self.home))

    def _check(self, restic: Restic, store: BackupStateStore) -> CheckResult:
        try:
            restic.run("check")
        except ResticError as exc:
            result = CheckResult(at=self.now(), ok=False, message=str(exc))
        else:
            result = CheckResult(at=self.now(), ok=True)
        state = store.load(restic.repository)
        store.save(state.model_copy(update={"last_check": result}))
        return result

    def _prune_due(self, state: BackupState) -> bool:
        return state.last_prune is None or self.now() - state.last_prune >= PRUNE_INTERVAL


@contextmanager
def _paused(gate: JobGate | None, run: _Run) -> Iterator[None]:
    """Wait for quiet, then hold background jobs for the block, and release
    them however it ends (spec, *Backup run* steps 1, 2 and 4)."""
    if gate is None:
        yield
        return
    gate.pause()
    run.step = "waiting"
    try:
        if not gate.wait_idle(waiting=lambda job: run.tell(BackupProgress("waiting", job))):
            raise _StoppedError("The app shut down before the backup started.")
        yield
    finally:
        gate.resume()


class _StoppedError(Exception):
    pass


@dataclass
class _Run:
    started_at: datetime
    repository: str
    tell: Progress
    step: BackupStep = "starting"
    snapshot_id: str | None = None
    failure: str | None = None
    stopped: bool = False
    warnings: list[str] = field(default_factory=list)

    def enter(self, step: BackupStep) -> None:
        self.step = step
        self.tell(BackupProgress(step))

    def hear(self, line: object) -> None:
        """One line of ``restic backup --json``."""
        if not isinstance(line, dict):
            return
        kind = line.get("message_type")
        if kind == "status":
            self.tell(
                BackupProgress(
                    "backing_up",
                    files_done=line.get("files_done", 0),
                    files_total=line.get("total_files"),
                )
            )
        elif kind == "summary":
            self.snapshot_id = line.get("snapshot_id")
        elif kind == "error":
            error = line.get("error") or {}
            self.warnings.append(f"{line.get('item', '')}: {error.get('message', '')}")

    def record(self, finished_at: datetime) -> RunRecord:
        outcome: RunOutcome = "stopped" if self.stopped else "failed"
        failed = self.failure is not None
        return RunRecord(
            repository=self.repository,
            started_at=self.started_at,
            finished_at=finished_at,
            outcome=outcome if failed else "succeeded",
            snapshot_id=self.snapshot_id,
            failed_step=self.step if failed else None,
            message=self.failure,
            warnings=tuple(self.warnings),
        )

"""One backup run: back up, forget, the weekly prune and check, then the
copy to each destination and its monthly check (workspace-backup spec,
*Backup run*; plan, PRs 3 and 4).

The server passes its :class:`JobGate`, so the run waits for quiet, pauses
the background jobs for the ``restic backup`` step alone and resumes them
whatever happened; the CLI passes none (spec, *CLI*). Each run, failed ones
included, is appended to the history in ``~/.etsy-listings``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from etsy_listings.core.application.backup_repository import (
    backup_settings,
    check_backup_paths,
    open_repository,
)
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import (
    SAMPLE_FRACTION,
    CopyHooks,
    CopyResult,
    CopyStep,
    DestinationCheck,
    RepairResult,
    check_destination,
    copy_repository,
    repair_destination,
)
from etsy_listings.core.backup.restic import Launch, Restic, ResticCancelledError, ResticError
from etsy_listings.core.backup.state import (
    BackupState,
    BackupStateStore,
    CheckResult,
    CopyRecord,
    DestinationState,
    RunOutcome,
    RunRecord,
)
from etsy_listings.core.config.settings import BackupSettings, RetentionSettings
from etsy_listings.core.errors import ConflictError, MissingError, UserFacingError
from etsy_listings.core.workspace.workspace import Workspace

Clock = Callable[[], datetime]
PARTIAL_SNAPSHOT_EXIT = 3
PRUNE_INTERVAL = timedelta(days=7)
"""Prune, then check, weekly (spec, *Backup run* step 6)."""
COPY_CHECK_INTERVAL = timedelta(days=30)
"""Each destination's sample check, monthly (spec, *Backup run* step 8)."""
BackupStep = Literal[
    "starting",
    "waiting",
    "backing_up",
    "forgetting",
    "pruning",
    "checking",
    "copying",
    "checking_copy",
]


@dataclass(frozen=True)
class BackupProgress:
    """Enough for the running line: the step, the job a backup waits for,
    files read out of the total while backing up, and the destination
    being copied or checked."""

    step: BackupStep
    waiting_for: str | None = None
    files_done: int | None = None
    files_total: int | None = None
    destination: str | None = None


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
    sample: float = SAMPLE_FRACTION
    """The share of a destination's files its monthly check reads."""

    def run(
        self,
        *,
        gate: JobGate | None = None,
        progress: Progress | None = None,
        cancel: threading.Event | None = None,
        maintenance: Callable[[], AbstractContextManager[bool]] | None = None,
    ) -> RunRecord:
        """Back up, forget, and prune and check when due. ``cancel`` stops
        restic part way; the run is then recorded as stopped. The server
        reserves exclusive maintenance or defers it while a restore runs."""
        settings = backup_settings(self.workspace)
        store = BackupStateStore(self.home)
        run = _Run(self.now(), str(settings.repository), progress or (lambda _: None))
        try:
            check_backup_paths(self.workspace, settings.repository, settings.destinations)
            restic = open_repository(
                self.workspace, binaries=self.binaries, launch=self.launch, settings=settings
            )
            with _paused(gate, run):
                run.enter("backing_up")
                self._back_up(restic, run, cancel)
            with maintenance() if maintenance else nullcontext(enter_result=True) as available:
                if available:
                    self._tidy(restic, settings, store, run, cancel)
                elif _needs_check(store.load(settings.repository)):
                    run.enter("checking")
                    run.failure = "The repository must pass a check before it can be copied."
            if run.failure is None:
                self._copy_all(settings, store, run, cancel)
        except (_StoppedError, ResticCancelledError) as exc:
            run.stopped, run.failure = True, str(exc)
        except UserFacingError as exc:
            run.failure = str(exc)
        except OSError as exc:
            run.failure = str(exc)
        record = run.record(self.now())
        store.append_run(record)
        return record

    def _tidy(
        self,
        restic: Restic,
        settings: BackupSettings,
        store: BackupStateStore,
        run: _Run,
        cancel: threading.Event | None,
    ) -> None:
        """Forget, then the weekly prune and check, each under restic's
        exclusive lock."""
        run.enter("forgetting")
        restic.run(*forget_arguments(settings.retention), cancel=cancel)
        state = store.load(settings.repository)
        prune = self._prune_due(state)
        if prune:
            run.enter("pruning")
            restic.run("prune", cancel=cancel)
            state = store.load(settings.repository)
            state = state.model_copy(update={"last_prune": self.now()})
            store.save(state)
        if prune or _needs_check(state):
            run.enter("checking")
            run.failure = self._check(restic, store, cancel=cancel).message

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

    def _copy_all(
        self,
        settings: BackupSettings,
        store: BackupStateStore,
        run: _Run,
        cancel: threading.Event | None,
    ) -> None:
        """Steps 7 and 8, after the jobs resumed. An unreachable or changed
        destination is recorded and the run goes on: the local backup still
        counts. A damaged local file is a failed check and ends the run."""
        for destination in settings.destinations:
            run.enter("copying", destination)
            result = self._copy_one(settings, store, destination, run, cancel)
            run.copies.append(
                CopyRecord(
                    destination=str(destination), outcome=result.outcome, message=result.message
                )
            )
            if result.outcome == "stopped":
                raise _StoppedError(result.message)
            if result.outcome == "damaged":
                run.failure = result.message
                state = store.load(settings.repository)
                damage = CheckResult(at=self.now(), ok=False, message=result.message)
                store.save(state.model_copy(update={"last_check": damage}))
                return

    def _copy_one(
        self,
        settings: BackupSettings,
        store: BackupStateStore,
        destination: Path,
        run: _Run,
        cancel: threading.Event | None,
    ) -> CopyResult:
        before = store.load(settings.repository).destination(destination)
        result = copy_repository(
            settings.repository,
            destination,
            suspect=_suspects(before),
            hooks=_CopyProgress(run, str(destination)).hooks(),
            cancel=cancel,
        )
        after = _after_copy(before, result, self.now())
        if result.outcome == "copied" and _copy_check_due(after, self.now()):
            run.enter("checking_copy", destination)
            check = check_destination(settings.repository, destination, fraction=self.sample)
            after = _after_check(after, check, self.now())
        store.save(store.load(settings.repository).with_destination(destination, after))
        return result

    def repair(self, destination: Path) -> RepairResult:
        """Set aside what changed in ``destination`` and copy it again
        (spec, *Changed and unexpected files*)."""
        settings = backup_settings(self.workspace)
        check_backup_paths(self.workspace, settings.repository, settings.destinations)
        if destination not in settings.destinations:
            raise MissingError(f"{destination} is not a destination in settings.yaml.")
        store = BackupStateStore(self.home)
        state = store.load(settings.repository)
        if _needs_check(state):
            raise ConflictError("The repository must pass a check before its copy can be repaired.")
        before = state.destination(destination)
        repair = repair_destination(
            settings.repository,
            destination,
            today=self.now().astimezone().date(),
            suspect=_suspects(before),
        )
        after = _after_copy(before.model_copy(update={"changed": ()}), repair.copy, self.now())
        store.save(store.load(settings.repository).with_destination(destination, after))
        return repair

    def check(self) -> CheckResult:
        """``restic check`` of the local repository, recorded in the state."""
        restic = open_repository(self.workspace, binaries=self.binaries, launch=self.launch)
        return self._check(restic, BackupStateStore(self.home))

    def _check(
        self, restic: Restic, store: BackupStateStore, *, cancel: threading.Event | None = None
    ) -> CheckResult:
        try:
            restic.run("check", cancel=cancel)
        except ResticCancelledError:
            raise
        except ResticError as exc:
            result = CheckResult(at=self.now(), ok=False, message=str(exc))
        else:
            result = CheckResult(at=self.now(), ok=True)
        state = store.load(restic.repository)
        store.save(state.model_copy(update={"last_check": result}))
        return result

    def _prune_due(self, state: BackupState) -> bool:
        return state.last_prune is None or self.now() - state.last_prune >= PRUNE_INTERVAL


def _needs_check(state: BackupState) -> bool:
    check = state.last_check
    if check is not None and not check.ok:
        return True
    pruned = state.last_prune
    return pruned is not None and (check is None or check.at < pruned)


def _suspects(state: DestinationState) -> frozenset[str]:
    """Changes that kept the size, which only a check can see, stay known
    until a repair."""
    return frozenset(file.name for file in state.changed if file.expected_size == file.actual_size)


def _after_copy(state: DestinationState, result: CopyResult, now: datetime) -> DestinationState:
    update: dict[str, object] = {"problem": result.message}
    if result.outcome == "copied":
        update |= {"last_copy": now, "changed": (), "unexpected": result.unexpected}
    elif result.outcome == "changed":
        update |= {"changed": result.changed, "unexpected": result.unexpected}
    return state.model_copy(update=update)


def _copy_check_due(state: DestinationState, now: datetime) -> bool:
    check = state.last_check
    return check is None or not check.ok or now - check.at >= COPY_CHECK_INTERVAL


def _after_check(
    state: DestinationState, check: DestinationCheck, now: datetime
) -> DestinationState:
    known = {file.name for file in state.changed}
    found = tuple(file for file in check.changed if file.name not in known)
    result = CheckResult(at=now, ok=check.outcome == "ok", message=check.message)
    return state.model_copy(update={"last_check": result, "changed": state.changed + found})


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
class _CopyProgress:
    """Files copied out of those the destination lacks, for the running
    line during a large first copy (plan, PR 5)."""

    run: _Run
    destination: str
    done: int = 0
    total: int = 0

    def hooks(self) -> CopyHooks:
        return CopyHooks(planned=self._planned, observe=self._observe)

    def _planned(self, total: int) -> None:
        self.total = total
        self._tell()

    def _observe(self, step: CopyStep) -> None:
        if step.action == "copied":
            self.done += 1
            self._tell()

    def _tell(self) -> None:
        self.run.tell(
            BackupProgress(
                "copying",
                files_done=self.done,
                files_total=self.total,
                destination=self.destination,
            )
        )


@dataclass
class _Run:
    started_at: datetime
    repository: str
    tell: Progress
    step: BackupStep = "starting"
    snapshot_id: str | None = None
    data_added: int | None = None
    failure: str | None = None
    stopped: bool = False
    warnings: list[str] = field(default_factory=list)
    copies: list[CopyRecord] = field(default_factory=list)

    def enter(self, step: BackupStep, destination: Path | None = None) -> None:
        self.step = step
        where = None if destination is None else str(destination)
        self.tell(BackupProgress(step, destination=where))

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
            self.data_added = line.get("data_added")
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
            data_added=self.data_added,
            copies=tuple(self.copies),
        )

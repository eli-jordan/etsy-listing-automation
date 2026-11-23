"""One backup run (workspace-backup spec, *Backup run*; plan, PR 3) with
restic replaced by recorded ``--json`` replies, so the gate, the step order,
the weekly prune and the state and history files are observable without
restic. ``home`` is under ``tmp_path`` throughout (plan, P2).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import backup_settings
from etsy_listings.core.application.backup_run import BackupProgress, BackupRunner
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.restic import ResticProcess
from etsy_listings.core.backup.state import (
    BackupState,
    BackupStateStore,
    CheckResult,
    CopyRecord,
    DestinationState,
    RunRecord,
)
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.repository_files import FakeRepository, files
from tests.support.restic import Reply, ScriptedRestic, exit_error

PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
SNAPSHOT_ID = "0d4f8513e5f5dcca2a2449d564c44f6bd0d367955d7cd12a9a6fda20efd1d717"

# restic 0.19.1's lines, trimmed to the keys the run reads.
STATUS = {
    "message_type": "status",
    "percent_done": 0.5,
    "total_files": 10,
    "files_done": 5,
    "total_bytes": 1000,
    "bytes_done": 500,
}
SUMMARY = {"message_type": "summary", "files_new": 1, "snapshot_id": SNAPSHOT_ID}
BACKED_UP = Reply(stdout=[STATUS, SUMMARY])
FORGOT = Reply(stdout=[[{"host": "pc", "keep": [], "remove": None}]])
PRUNED = Reply(stdout=["loading all snapshots...", "done"])
CHECKED = Reply(stdout=[{"message_type": "summary", "num_errors": 0}])


class GateWatchingRestic(ScriptedRestic):
    """Records whether the gate was paused when each command started."""

    def __init__(self, gate: JobGate, *replies: Reply) -> None:
        super().__init__(*replies)
        self.gate = gate
        self.paused_at_launch: list[bool] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> ResticProcess:
        self.paused_at_launch.append(self.gate.paused)
        return super().__call__(argv, env)


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)


@pytest.fixture
def workspace(workspace_root: Path, tmp_path: Path) -> Workspace:
    workspace_root.joinpath("settings.yaml").write_text(
        f"backup:\n  repository: {(tmp_path / 'backups').as_posix()}\n"
        f"  restic_binary: {(tmp_path / 'restic').as_posix()}\n",
        encoding="utf-8",
    )
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _run(
    workspace: Workspace,
    home: Path,
    launcher: ScriptedRestic,
    *,
    gate: JobGate | None = None,
    now: datetime = NOW,
) -> RunRecord:
    runner = BackupRunner(
        workspace,
        ResticBinaries(home=home),
        home=home,
        launch=launcher,
        now=lambda: now,
        sample=1.0,  # every file, so a check always finds a change
    )
    return runner.run(gate=gate)


def _state(workspace: Workspace, home: Path) -> BackupState:
    return BackupStateStore(home).load(backup_settings(workspace).repository)


def test_jobs_are_paused_only_for_the_backup_step(workspace: Workspace, home: Path) -> None:
    gate = JobGate()
    launcher = GateWatchingRestic(gate, BACKED_UP, FORGOT, PRUNED, CHECKED)

    record = _run(workspace, home, launcher, gate=gate)

    assert record.outcome == "succeeded"
    assert record.snapshot_id == SNAPSHOT_ID
    assert [command[0] for command in launcher.commands] == ["backup", "forget", "prune", "check"]
    assert launcher.paused_at_launch == [True, False, False, False]
    assert not gate.paused


def test_a_failed_backup_resumes_jobs_and_is_recorded(workspace: Workspace, home: Path) -> None:
    gate = JobGate()
    locked = Reply(exit_code=11, stderr=exit_error(11, "repository is already locked by PID 7"))
    launcher = GateWatchingRestic(gate, locked)

    record = _run(workspace, home, launcher, gate=gate)

    assert not gate.paused
    assert (record.outcome, record.failed_step, record.snapshot_id) == (
        "failed",
        "backing_up",
        None,
    )
    assert "already locked" in (record.message or "")
    assert BackupStateStore(home).runs() == [record]


def test_prune_and_check_run_only_once_7_days_have_passed(workspace: Workspace, home: Path) -> None:
    weekly = ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED)
    _run(workspace, home, weekly, now=NOW)
    six_days = ScriptedRestic(BACKED_UP, FORGOT)
    _run(workspace, home, six_days, now=NOW + timedelta(days=6, hours=23))
    seven_days = ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED)
    _run(workspace, home, seven_days, now=NOW + timedelta(days=7))

    assert [c[0] for c in weekly.commands] == ["backup", "forget", "prune", "check"]
    assert [c[0] for c in six_days.commands] == ["backup", "forget"]
    assert [c[0] for c in seven_days.commands] == ["backup", "forget", "prune", "check"]
    state = _state(workspace, home)
    assert state.last_prune == NOW + timedelta(days=7)
    assert state.last_check == CheckResult(at=NOW + timedelta(days=7), ok=True)


def test_the_run_waits_for_work_in_flight_and_reports_each_step(
    workspace: Workspace, home: Path
) -> None:
    gate = JobGate()
    ticket = gate.admit("deploy plan")
    assert ticket is not None
    launcher = ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED)
    heard: list[BackupProgress] = []
    runner = BackupRunner(workspace, ResticBinaries(home=home), home=home, launch=launcher)
    worker = threading.Thread(target=lambda: runner.run(gate=gate, progress=heard.append))
    worker.start()
    deadline = time.monotonic() + 5
    while not heard and time.monotonic() < deadline:
        time.sleep(0.01)

    assert heard == [BackupProgress("waiting", waiting_for="deploy plan")]
    assert launcher.launches == []
    ticket.release()
    worker.join(timeout=5)
    assert heard[1:] == [
        BackupProgress("backing_up"),
        BackupProgress("backing_up", files_done=5, files_total=10),
        BackupProgress("forgetting"),
        BackupProgress("pruning"),
        BackupProgress("checking"),
    ]


def test_shutdown_while_waiting_ends_the_run_without_backing_up(
    workspace: Workspace, home: Path
) -> None:
    gate = JobGate()
    gate.admit("AI run")
    gate.stop()

    record = _run(workspace, home, ScriptedRestic(), gate=gate)

    assert (record.outcome, record.failed_step) == ("stopped", "waiting")
    assert BackupStateStore(home).runs() == [record]


def test_files_restic_could_not_read_are_warnings_on_a_successful_run(
    workspace: Workspace, home: Path
) -> None:
    unreadable = {
        "message_type": "error",
        "error": {"message": "The process cannot access the file"},
        "during": "archival",
        "item": "C:\\workspace\runs.db",
    }
    partial = Reply(
        stdout=[unreadable, SUMMARY],
        exit_code=3,
        stderr=exit_error(3, "Warning: at least one source file could not be read"),
    )

    record = _run(workspace, home, ScriptedRestic(partial, FORGOT, PRUNED, CHECKED))

    assert (record.outcome, record.snapshot_id) == ("succeeded", SNAPSHOT_ID)
    assert record.warnings == ("C:\\workspace\runs.db: The process cannot access the file",)


def test_a_run_without_the_password_is_recorded_as_failed(workspace: Workspace, home: Path) -> None:
    (workspace.root / layout.ENV_FILE).unlink()

    record = _run(workspace, home, ScriptedRestic())

    assert (record.outcome, record.failed_step) == ("failed", "starting")
    assert BACKUP_PASSWORD_VAR in (record.message or "")
    assert BackupStateStore(home).runs() == [record]


def test_cancelling_part_way_stops_restic_and_resumes_jobs(
    workspace: Workspace, home: Path
) -> None:
    gate = JobGate()
    cancel = threading.Event()
    launcher = ScriptedRestic(Reply(stdout=[STATUS], hang=True))
    runner = BackupRunner(workspace, ResticBinaries(home=home), home=home, launch=launcher)

    def cancel_once_reading(progress: BackupProgress) -> None:
        if progress.files_done is not None:
            cancel.set()

    record = runner.run(gate=gate, progress=cancel_once_reading, cancel=cancel)

    assert (record.outcome, record.failed_step) == ("stopped", "backing_up")
    assert launcher.processes[0].stopped.is_set()
    assert not gate.paused


def test_a_failed_check_fails_the_run_and_is_recorded(workspace: Workspace, home: Path) -> None:
    damaged = Reply(exit_code=1, stderr=exit_error(1, "pack 5f2b: not referenced in any index"))

    record = _run(workspace, home, ScriptedRestic(BACKED_UP, FORGOT, PRUNED, damaged))

    assert (record.outcome, record.failed_step, record.snapshot_id) == (
        "failed",
        "checking",
        SNAPSHOT_ID,
    )
    check = _state(workspace, home).last_check
    assert check is not None
    assert not check.ok
    assert "not referenced" in (check.message or "")


def _with_destinations(workspace: Workspace, *destinations: Path) -> Workspace:
    settings = workspace.root / "settings.yaml"
    listed = "".join(f"    - {path.as_posix()}\n" for path in destinations)
    settings.write_text(
        settings.read_text(encoding="utf-8") + f"  destinations:\n{listed}", encoding="utf-8"
    )
    return Workspace.discover(root_override=workspace.root)


@pytest.fixture
def repository(tmp_path: Path) -> FakeRepository:
    """The backup storage folder's files; restic itself is scripted."""
    local = FakeRepository(tmp_path / "backups")
    local.backup("first")
    return local


def _destination_state(workspace: Workspace, home: Path, destination: Path) -> DestinationState:
    return _state(workspace, home).destinations[str(destination)]


def test_each_destination_is_copied_after_jobs_resume(
    workspace: Workspace, home: Path, repository: FakeRepository, tmp_path: Path
) -> None:
    icloud, nas = tmp_path / "icloud" / "backups", tmp_path / "nas" / "backups"
    icloud.parent.mkdir()
    nas.parent.mkdir()
    workspace = _with_destinations(workspace, icloud, nas)
    gate = JobGate()
    heard: list[BackupProgress] = []
    runner = BackupRunner(
        workspace,
        ResticBinaries(home=home),
        home=home,
        launch=ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED),
        now=lambda: NOW,
    )

    record = runner.run(gate=gate, progress=heard.append)

    assert record.outcome == "succeeded"
    assert record.copies == (
        CopyRecord(destination=str(icloud), outcome="copied"),
        CopyRecord(destination=str(nas), outcome="copied"),
    )
    assert files(icloud) == files(nas) == files(repository.root)
    steps = [p.step for p in heard if p.files_done is None]
    assert steps[-4:] == ["copying", "checking_copy", "copying", "checking_copy"]
    assert [p.destination for p in heard[-4:]] == [str(icloud)] * 2 + [str(nas)] * 2
    assert _destination_state(workspace, home, icloud).last_copy == NOW


def test_an_unreachable_destination_is_skipped_and_the_backup_still_succeeds(
    workspace: Workspace, home: Path, repository: FakeRepository, tmp_path: Path
) -> None:
    offline, icloud = tmp_path / "nas" / "backups", tmp_path / "icloud"
    icloud.mkdir()
    workspace = _with_destinations(workspace, offline, icloud)

    record = _run(workspace, home, ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED))

    assert record.outcome == "succeeded"
    assert [copy.outcome for copy in record.copies] == ["unreachable", "copied"]
    assert files(icloud) == files(repository.root)
    unreachable = _destination_state(workspace, home, offline)
    assert unreachable.last_copy is None
    assert str(offline) in (unreachable.problem or "")


def test_each_destination_is_checked_once_30_days_have_passed(
    workspace: Workspace, home: Path, repository: FakeRepository, tmp_path: Path
) -> None:
    icloud = tmp_path / "icloud"
    workspace = _with_destinations(workspace, icloud)
    weekly = (BACKED_UP, FORGOT, PRUNED, CHECKED)

    _run(workspace, home, ScriptedRestic(*weekly), now=NOW)
    _run(workspace, home, ScriptedRestic(*weekly), now=NOW + timedelta(days=29, hours=23))
    first = _destination_state(workspace, home, icloud).last_check
    _run(workspace, home, ScriptedRestic(*weekly), now=NOW + timedelta(days=30))
    second = _destination_state(workspace, home, icloud).last_check

    assert first == CheckResult(at=NOW, ok=True)
    assert second == CheckResult(at=NOW + timedelta(days=30), ok=True)


def test_a_change_the_check_found_stops_copying_until_the_destination_is_repaired(
    workspace: Workspace, home: Path, repository: FakeRepository, tmp_path: Path
) -> None:
    icloud = tmp_path / "icloud"
    workspace = _with_destinations(workspace, icloud)
    [pack] = [name for name in files(repository.root) if name.startswith("data/")]
    weekly = (BACKED_UP, FORGOT, PRUNED, CHECKED)
    _run(workspace, home, ScriptedRestic(*weekly), now=NOW)
    (icloud / pack).write_bytes((icloud / pack).read_bytes().upper())
    later = NOW + timedelta(days=30)

    found = _run(workspace, home, ScriptedRestic(*weekly), now=later)
    stopped = _run(workspace, home, ScriptedRestic(BACKED_UP, FORGOT), now=later)
    state = _destination_state(workspace, home, icloud)
    runner = BackupRunner(workspace, ResticBinaries(home=home), home=home, now=lambda: later)
    repair = runner.repair(icloud)

    assert found.copies[0].outcome == "copied"
    assert stopped.copies[0].outcome == "changed"
    assert [file.name for file in state.changed] == [pack]
    assert repair.moved == (pack,)
    repaired = _destination_state(workspace, home, icloud)
    assert (repaired.changed, repaired.unexpected, repaired.last_copy) == ((), (), later)
    assert files(icloud) == files(repository.root)


def test_a_damaged_local_file_fails_the_run_as_a_failed_check(
    workspace: Workspace, home: Path, repository: FakeRepository, tmp_path: Path
) -> None:
    icloud = tmp_path / "icloud"
    workspace = _with_destinations(workspace, icloud)
    pack, _, _ = repository.backup("second")
    (repository.root / pack).write_bytes(b"pack:bit rot")

    record = _run(workspace, home, ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED))

    assert (record.outcome, record.failed_step) == ("failed", "copying")
    assert pack in (record.message or "")
    check = _state(workspace, home).last_check
    assert check is not None
    assert not check.ok
    assert pack in (check.message or "")


def test_stopping_while_copying_records_the_run_as_stopped(
    workspace: Workspace, home: Path, repository: FakeRepository, tmp_path: Path
) -> None:
    icloud, nas = tmp_path / "icloud", tmp_path / "nas"
    workspace = _with_destinations(workspace, icloud, nas)
    cancel = threading.Event()
    launcher = ScriptedRestic(BACKED_UP, FORGOT, PRUNED, CHECKED)
    runner = BackupRunner(workspace, ResticBinaries(home=home), home=home, launch=launcher)

    def stop_when_copying(progress: BackupProgress) -> None:
        if progress.step == "copying":
            cancel.set()

    record = runner.run(progress=stop_when_copying, cancel=cancel)

    assert (record.outcome, record.failed_step) == ("stopped", "copying")
    assert [copy.outcome for copy in record.copies] == ["stopped"]
    assert not (nas / "config").exists()

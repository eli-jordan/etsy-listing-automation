"""The restore job on the backup coordinator (workspace-backup spec,
*Restore*; plan, PR 7), against the in-memory repository: its status, one
at a time, beside backups but not maintenance, stop and shutdown. What a
restore refuses is test_backup_restore.py's. ``home`` is under ``tmp_path``
throughout (plan, P2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_coordinator import (
    BackupCoordinator,
    BackupEnvironment,
)
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.backup.state import BackupState, BackupStateStore, CheckResult
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.errors import ConflictError
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import wait_for
from tests.support.backups import configure_backups
from tests.support.restic import InMemoryRestic, snapshot_id

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
SNAPSHOT = snapshot_id(1)


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    path = tmp_path / "backups"
    path.mkdir()
    (path / "config").write_bytes(b"{}")
    return path


@pytest.fixture
def workspace(workspace_root: Path, repository: Path, tmp_path: Path) -> Workspace:
    return configure_backups(workspace_root, repository, restic_binary=tmp_path / "restic")


@pytest.fixture
def restic() -> InMemoryRestic:
    fake = InMemoryRestic(lambda: NOW)
    fake.snapshots.append(NOW - timedelta(hours=2))
    return fake


@pytest.fixture
def coordinator(workspace: Workspace, restic: InMemoryRestic, tmp_path: Path) -> BackupCoordinator:
    environment = BackupEnvironment(home=tmp_path / "home", restic=restic, now=lambda: NOW)
    return BackupCoordinator(workspace, gate=None, environment=environment)


def _files_done(coordinator: BackupCoordinator) -> int | None:
    restore = coordinator.overview().restore
    return None if restore is None else restore.files_done


def test_a_restore_runs_on_its_own_thread_and_its_status_follows_it(
    coordinator: BackupCoordinator, restic: InMemoryRestic, tmp_path: Path
) -> None:
    release = restic.hold("restore")
    target = tmp_path / "restored"

    coordinator.start_restore(SNAPSHOT[:8], target)
    wait_for(lambda: _files_done(coordinator) == 100)
    running = coordinator.overview().restore
    release.set()
    coordinator.join_restore(timeout=10)

    assert running is not None
    assert (running.outcome, running.fraction, running.bytes_total) == ("running", 0.25, 8_000_000)
    assert (running.snapshot_id, running.seconds_left) == (SNAPSHOT, 180)
    done = coordinator.overview().restore
    assert done is not None
    assert (done.outcome, done.files_done, done.target) == ("succeeded", 400, str(target))


def test_a_refusal_just_before_restic_writes_is_the_restore_s_failure(
    coordinator: BackupCoordinator, restic: InMemoryRestic, tmp_path: Path
) -> None:
    target = tmp_path / "restored"
    target.mkdir()

    def a_file_lands(operation: str) -> None:
        if operation == "snapshots":
            (target / "notes.txt").write_text("preserve me")

    restic.on_start = a_file_lands
    coordinator.start_restore(SNAPSHOT, target)
    coordinator.join_restore(timeout=10)

    result = coordinator.overview().restore
    assert result is not None
    assert (result.outcome, restic.ran("restore")) == ("failed", 0)
    assert "already holds files" in (result.message or "")


def test_one_restore_at_a_time(
    coordinator: BackupCoordinator, restic: InMemoryRestic, tmp_path: Path
) -> None:
    restic.hold("restore")
    coordinator.start_restore(SNAPSHOT, tmp_path / "first")
    try:
        with pytest.raises(ConflictError):
            coordinator.start_restore(SNAPSHOT, tmp_path / "second")
    finally:
        coordinator.stop_restore()


def test_stop_ends_the_restore_part_way_and_says_how_far_it_got(
    coordinator: BackupCoordinator, restic: InMemoryRestic, tmp_path: Path
) -> None:
    restic.hold("restore")
    coordinator.start_restore(SNAPSHOT, tmp_path / "restored")
    wait_for(lambda: _files_done(coordinator) == 100)

    coordinator.stop_restore()

    stopped = coordinator.overview().restore
    assert stopped is not None
    assert (stopped.outcome, stopped.fraction) == ("stopped", 0.25)
    assert restic.stopped("restore") == 1


def test_shutting_down_stops_a_restore(
    coordinator: BackupCoordinator, restic: InMemoryRestic, tmp_path: Path
) -> None:
    restic.hold("restore")
    coordinator.start_restore(SNAPSHOT, tmp_path / "restored")

    coordinator.stop()

    stopped = coordinator.overview().restore
    assert stopped is not None
    assert stopped.outcome == "stopped"


def test_a_scheduled_backup_runs_during_a_restore_and_the_weekly_prune_waits(
    coordinator: BackupCoordinator, restic: InMemoryRestic, repository: Path, tmp_path: Path
) -> None:
    """restore's shared lock lets a backup in, but forget, prune and check
    need restic's exclusive lock, so they wait for the next run after it."""
    restic.snapshots[0] = NOW - timedelta(days=1)
    store = BackupStateStore(tmp_path / "home")
    pruned = NOW - timedelta(days=8)
    store.save(
        BackupState(
            repository=str(repository),
            last_prune=pruned,
            last_check=CheckResult(at=pruned, ok=True),
        )
    )
    release = restic.hold("restore")
    coordinator.start_restore(SNAPSHOT, tmp_path / "restored")
    wait_for(lambda: restic.ran("restore") == 1)

    assert coordinator.start_if_due()
    coordinator.join(timeout=10)
    during = {name: restic.ran(name) for name in ("back_up", "forget", "prune", "check")}
    release.set()
    coordinator.join_restore(timeout=10)
    coordinator.run_now()
    coordinator.join(timeout=10)

    assert during == {"back_up": 1, "forget": 0, "prune": 0, "check": 0}
    assert (restic.ran("back_up"), restic.ran("prune"), restic.ran("check")) == (2, 1, 1)
    assert coordinator.history()[1].run.outcome == "succeeded"


def test_a_restore_waits_for_maintenance_already_underway(
    coordinator: BackupCoordinator, restic: InMemoryRestic, tmp_path: Path
) -> None:
    release = restic.hold("forget")
    coordinator.run_now()
    try:
        wait_for(lambda: restic.ran("forget") == 1)
        coordinator.start_restore(SNAPSHOT, tmp_path / "restored")
        assert coordinator.restoring
    finally:
        release.set()
        coordinator.join(timeout=10)
        coordinator.join_restore(timeout=10)
        coordinator.stop()

    assert restic.operations.index("restore") > restic.operations.index("check")

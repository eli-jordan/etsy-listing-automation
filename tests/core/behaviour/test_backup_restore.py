"""The restore job on the backup coordinator (workspace-backup spec,
*Restore*; plan, PR 7), with the by-command fake restic. ``home`` is under
``tmp_path`` throughout (plan, P2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_coordinator import (
    BackupCoordinator,
    BackupEnvironment,
)
from etsy_listings.core.application.backup_restore import RestoreRefusedError
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.backup.state import BackupState, BackupStateStore
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.errors import ConflictError, MissingError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import wait_for
from tests.support.restic import RepositoryRestic

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
SNAPSHOT = f"{1:064x}"


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
    workspace_root.joinpath("settings.yaml").write_text(
        f"backup:\n  repository: {repository.as_posix()}\n"
        f"  restic_binary: {(tmp_path / 'restic').as_posix()}\n",
        encoding="utf-8",
    )
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}=correct horse battery\n")
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def restic(repository: Path) -> RepositoryRestic:
    fake = RepositoryRestic(repository, lambda: NOW)
    fake.snapshots.append(NOW - timedelta(hours=2))
    return fake


@pytest.fixture
def coordinator(
    workspace: Workspace, restic: RepositoryRestic, tmp_path: Path
) -> BackupCoordinator:
    environment = BackupEnvironment(home=tmp_path / "home", launch=restic, now=lambda: NOW)
    return BackupCoordinator(workspace, gate=None, environment=environment)


def _files_done(coordinator: BackupCoordinator) -> int | None:
    restore = coordinator.overview().restore
    return None if restore is None else restore.files_done


def _restore_command(restic: RepositoryRestic) -> list[str]:
    return next(command for command in restic.commands if command[0] == "restore")


def test_a_restore_writes_the_snapshot_into_a_new_folder_and_reports_progress(
    coordinator: BackupCoordinator, restic: RepositoryRestic, tmp_path: Path
) -> None:
    restic.restore_hang = True
    target = tmp_path / "restored"

    coordinator.start_restore(SNAPSHOT[:8], target)
    wait_for(lambda: _files_done(coordinator) == 100)
    running = coordinator.overview().restore
    restic.restore_release.set()
    coordinator.join_restore(timeout=10)

    assert _restore_command(restic)[1:4] == [f"{SNAPSHOT}:/workspace", "--target", str(target)]
    assert running is not None
    assert (running.outcome, running.percent, running.bytes_total) == ("running", 0.25, 8_000_000)
    assert running.seconds_left == 180, "a quarter done in a minute leaves three"
    done = coordinator.overview().restore
    assert done is not None
    assert (done.outcome, done.files_done, done.target) == ("succeeded", 400, str(target))


@pytest.mark.parametrize("where", ["workspace", "inside", "non_empty"])
def test_a_restore_refuses_the_live_workspace_and_a_folder_with_files(
    coordinator: BackupCoordinator,
    restic: RepositoryRestic,
    workspace: Workspace,
    tmp_path: Path,
    where: str,
) -> None:
    full = tmp_path / "full"
    full.mkdir()
    (full / "notes.txt").write_text("keep me")
    target = {"workspace": workspace.root, "inside": workspace.root / "old", "non_empty": full}

    with pytest.raises(RestoreRefusedError):
        coordinator.start_restore(SNAPSHOT, target[where])

    assert restic.ran("restore") == 0
    assert coordinator.overview().restore is None


def test_an_unknown_snapshot_is_missing(
    coordinator: BackupCoordinator, restic: RepositoryRestic, tmp_path: Path
) -> None:
    with pytest.raises(MissingError):
        coordinator.start_restore("deadbeef", tmp_path / "restored")
    assert restic.ran("restore") == 0


def test_one_restore_at_a_time(
    coordinator: BackupCoordinator, restic: RepositoryRestic, tmp_path: Path
) -> None:
    restic.restore_hang = True
    coordinator.start_restore(SNAPSHOT, tmp_path / "first")
    try:
        with pytest.raises(ConflictError):
            coordinator.start_restore(SNAPSHOT, tmp_path / "second")
    finally:
        coordinator.stop_restore()


def test_stop_ends_the_restore_part_way_and_says_how_far_it_got(
    coordinator: BackupCoordinator, restic: RepositoryRestic, tmp_path: Path
) -> None:
    restic.restore_hang = True
    coordinator.start_restore(SNAPSHOT, tmp_path / "restored")
    wait_for(lambda: _files_done(coordinator) == 100)

    coordinator.stop_restore()

    stopped = coordinator.overview().restore
    assert stopped is not None
    assert (stopped.outcome, stopped.percent) == ("stopped", 0.25)
    assert restic.stopped("restore") == 1


def test_shutting_down_stops_a_restore(
    coordinator: BackupCoordinator, restic: RepositoryRestic, tmp_path: Path
) -> None:
    restic.restore_hang = True
    coordinator.start_restore(SNAPSHOT, tmp_path / "restored")

    coordinator.stop()

    stopped = coordinator.overview().restore
    assert stopped is not None
    assert stopped.outcome == "stopped"


def test_a_scheduled_backup_runs_during_a_restore_and_the_weekly_prune_waits(
    coordinator: BackupCoordinator, restic: RepositoryRestic, tmp_path: Path
) -> None:
    """restore's shared lock lets a backup in, but forget, prune and check
    need restic's exclusive lock, so they wait for the next run after it."""
    restic.snapshots[0] = NOW - timedelta(days=1)
    store = BackupStateStore(tmp_path / "home")
    store.save(BackupState(repository=str(restic.repository), last_prune=NOW - timedelta(days=8)))
    restic.restore_hang = True
    coordinator.start_restore(SNAPSHOT, tmp_path / "restored")
    wait_for(lambda: restic.ran("restore") == 1)

    assert coordinator.check()
    coordinator.join(timeout=10)
    during = [command[0] for command in restic.commands if command[0] != "snapshots"]
    restic.restore_release.set()
    coordinator.join_restore(timeout=10)
    coordinator.run_now()
    coordinator.join(timeout=10)
    after = [command[0] for command in restic.commands if command[0] != "snapshots"]

    assert during == ["restore", "backup"]
    assert after[len(during) :] == ["backup", "forget", "prune", "check"]
    assert coordinator.history()[1].run.outcome == "succeeded"

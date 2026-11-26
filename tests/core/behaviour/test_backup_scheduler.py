"""The server's backup scheduler (workspace-backup spec, *Scope and
decisions*, Scheduling and Manual run; plan, PR 5), driven by a fake clock:
nothing here sleeps for an interval. The repository is in memory and shared
by every open, so the scheduler's own snapshot reads and its runs can
interleave. ``home`` is
under ``tmp_path`` throughout (plan, P2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_coordinator import (
    BackupBusyError,
    BackupCoordinator,
    BackupEnvironment,
)
from etsy_listings.core.application.backup_overview import RETRY_AFTER
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.backup.repository import RepositoryLockedError
from etsy_listings.core.backup.state import BackupState, BackupStateStore
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.errors import ConflictError
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.ai_runs import wait_for
from tests.support.backups import configure_backups
from tests.support.restic import InMemoryRestic

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def _settings(workspace_root: Path, repository: Path, tmp_path: Path, *, hours: int = 12) -> None:
    configure_backups(
        workspace_root, repository, restic_binary=tmp_path / "restic", interval_hours=hours
    )


@pytest.fixture
def workspace(workspace_root: Path, repository: Path, tmp_path: Path) -> Workspace:
    _settings(workspace_root, repository, tmp_path)
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def restic(repository: Path, clock: Clock, tmp_path: Path) -> InMemoryRestic:
    fake = InMemoryRestic(clock)
    repository.mkdir()
    (repository / "config").write_bytes(b"{}")
    # The weekly prune is not due, so a run is backup then forget.
    BackupStateStore(tmp_path / "home").save(
        BackupState(repository=str(repository), last_prune=NOW)
    )
    return fake


@pytest.fixture
def coordinator(
    workspace: Workspace, restic: InMemoryRestic, clock: Clock, tmp_path: Path
) -> BackupCoordinator:
    environment = BackupEnvironment(home=tmp_path / "home", restic=restic, now=clock)
    return BackupCoordinator(workspace, gate=JobGate(), environment=environment)


def _ran(coordinator: BackupCoordinator, restic: InMemoryRestic) -> bool:
    started = coordinator.start_if_due()
    coordinator.join(timeout=10)
    assert started == (restic.ran("back_up") > 0)
    return started


def test_a_backup_is_due_the_interval_after_the_last_success(
    coordinator: BackupCoordinator, restic: InMemoryRestic, clock: Clock
) -> None:
    restic.snapshots.append(NOW)

    clock.now = NOW + timedelta(hours=11, minutes=59)
    assert not _ran(coordinator, restic)

    clock.now = NOW + timedelta(hours=12)
    assert _ran(coordinator, restic)
    assert coordinator.overview().next_due == clock.now + timedelta(hours=12)


def test_a_repository_with_no_snapshot_is_due_at_once(
    coordinator: BackupCoordinator, restic: InMemoryRestic
) -> None:
    assert _ran(coordinator, restic)


def test_an_overdue_backup_runs_on_start_up(
    coordinator: BackupCoordinator, restic: InMemoryRestic
) -> None:
    restic.snapshots.append(NOW - timedelta(days=2))

    coordinator.start()
    try:
        wait_for(lambda: restic.ran("forget") == 1)
    finally:
        coordinator.stop()

    assert restic.ran("back_up") == 1


def test_nothing_starts_while_a_run_is_in_progress(
    coordinator: BackupCoordinator, restic: InMemoryRestic, clock: Clock
) -> None:
    restic.hold("back_up")
    assert coordinator.start_if_due()
    wait_for(lambda: restic.ran("back_up") == 1)

    clock.now = NOW + timedelta(days=3)
    assert not coordinator.start_if_due()
    with pytest.raises(BackupBusyError) as refused:
        coordinator.run_now()
    assert isinstance(refused.value, ConflictError)
    assert coordinator.overview().running is not None

    coordinator.stop()
    assert restic.ran("back_up") == 1
    assert coordinator.overview().running is None


def test_a_changed_interval_takes_effect_on_the_next_check(
    *,
    coordinator: BackupCoordinator,
    restic: InMemoryRestic,
    clock: Clock,
    workspace_root: Path,
    repository: Path,
    tmp_path: Path,
) -> None:
    restic.snapshots.append(NOW)
    clock.now = NOW + timedelta(hours=5)
    assert not _ran(coordinator, restic)

    _settings(workspace_root, repository, tmp_path, hours=4)

    assert _ran(coordinator, restic)


def test_a_failed_run_is_tried_again_an_hour_later_not_at_every_check(
    coordinator: BackupCoordinator, restic: InMemoryRestic, clock: Clock
) -> None:
    restic.fail("back_up", RepositoryLockedError("restic: repository is locked", exit_code=11))
    assert _ran(coordinator, restic)

    clock.now = NOW + RETRY_AFTER - timedelta(minutes=1)
    assert not coordinator.start_if_due()

    clock.now = NOW + RETRY_AFTER
    assert coordinator.start_if_due()
    coordinator.join(timeout=10)
    assert restic.ran("back_up") == 2


def test_back_up_now_runs_whenever_nothing_else_is(
    coordinator: BackupCoordinator, restic: InMemoryRestic
) -> None:
    restic.snapshots.append(NOW)

    coordinator.run_now()
    coordinator.join(timeout=10)

    assert restic.ran("back_up") == 1
    assert coordinator.overview().last_success == NOW


def test_nothing_runs_while_backups_are_off_or_the_repository_is_missing(
    coordinator: BackupCoordinator,
    restic: InMemoryRestic,
    workspace_root: Path,
    repository: Path,
) -> None:
    (repository / "config").unlink()
    assert not _ran(coordinator, restic)
    repository_overview = coordinator.overview().repository
    assert repository_overview is not None
    assert repository_overview.missing

    workspace_root.joinpath("settings.yaml").write_text("", encoding="utf-8")
    assert not _ran(coordinator, restic)
    assert restic.operations == []

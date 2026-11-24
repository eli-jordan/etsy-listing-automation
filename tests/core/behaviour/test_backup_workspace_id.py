"""The workspace ID: every snapshot is tagged with it, and the retention
keeps and groups this workspace's snapshots by it (workspace-backup spec,
*Backup run* step 5; ADR-0060). Against the in-memory repository; ``home``
is under ``tmp_path`` (plan, P2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import backup_settings
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.backups import configure_backups
from tests.support.restic import InMemoryRestic, MemorySnapshot

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
OURS = "6a1f3c0e-2b9d-4e5a-8c7f-0d1e2f3a4b5c"
THEIRS = "b2c4d6e8-1a3b-4c5d-9e7f-a0b1c2d3e4f5"
RETENTION = RetentionSettings(keep_within_days=7, weekly=1, monthly=1)
"""Two weeks and two months besides the last seven days."""


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def restic() -> InMemoryRestic:
    return InMemoryRestic(lambda: NOW)


def _workspace(root: Path, tmp_path: Path, workspace_id: str | None) -> Workspace:
    return configure_backups(
        root,
        tmp_path / "backups",
        restic_binary=tmp_path / "restic",
        workspace_id=workspace_id,
        retention=RETENTION,
    )


def _run(workspace: Workspace, home: Path, restic: InMemoryRestic) -> None:
    runner = BackupRunner(
        workspace, ResticBinaries(home=home), home=home, restic=restic, now=lambda: NOW
    )
    record = runner.run()
    assert record.outcome == "succeeded", record.message


def _days_ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def test_a_workspace_without_an_id_gets_one_once_and_tags_every_backup_with_it(
    workspace_root: Path, tmp_path: Path, home: Path, restic: InMemoryRestic
) -> None:
    workspace = _workspace(workspace_root, tmp_path, None)

    _run(workspace, home, restic)
    first = backup_settings(workspace).workspace_id
    _run(workspace, home, restic)

    assert first is not None
    assert str(uuid.UUID(first)) == first
    assert backup_settings(workspace).workspace_id == first
    assert len(restic.workspace_snapshots(first)) == 2


def test_snapshots_from_another_host_or_folder_age_out_on_the_same_schedule(
    workspace_root: Path, tmp_path: Path, home: Path, restic: InMemoryRestic
) -> None:
    """The PC was renamed and the workspace moved: the old snapshots carry
    the same ID, so they share the new ones' schedule."""
    workspace = _workspace(workspace_root, tmp_path, OURS)
    old_machine = [
        MemorySnapshot(_days_ago(days), OURS, hostname="old-pc", path="/icloud/workspace")
        for days in (120, 90, 60, 40, 20, 3)
    ]
    restic.snapshots.extend(old_machine)
    restic.hostname = "new-pc"

    _run(workspace, home, restic)

    left = restic.workspace_snapshots(OURS)
    assert {entry.time for entry in left} == {_days_ago(40), _days_ago(3), NOW}
    assert {entry.hostname for entry in left} == {"old-pc", "new-pc"}


def test_other_workspaces_and_untagged_snapshots_survive_forget(
    workspace_root: Path, tmp_path: Path, home: Path, restic: InMemoryRestic
) -> None:
    workspace = _workspace(workspace_root, tmp_path, OURS)
    theirs = [MemorySnapshot(_days_ago(days), THEIRS) for days in (300, 200, 100)]
    by_hand = [_days_ago(400), _days_ago(250)]
    restic.snapshots.extend([*theirs, *by_hand])
    restic.snapshots.extend(MemorySnapshot(_days_ago(days), OURS) for days in (300, 200))

    _run(workspace, home, restic)

    assert restic.workspace_snapshots(THEIRS) == theirs
    assert all(time in restic.snapshots for time in by_hand)
    # The older of this workspace's own goes; weekly and monthly keep the other.
    assert {entry.time for entry in restic.workspace_snapshots(OURS)} == {_days_ago(200), NOW}

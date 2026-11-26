"""The workspace ID: every snapshot is tagged with it, and the retention
keeps and groups this workspace's snapshots by it (workspace-backup spec,
*Backup run* step 5; ADR-0061). Against the in-memory repository; ``home``
is under ``tmp_path`` (plan, P2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.backup_repository import (
    SEVERAL_WORKSPACES,
    WorkspaceId,
    backup_settings,
    ensure_workspace_id,
)
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.state import RunRecord
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


def test_a_workspace_without_an_id_adopts_the_one_its_repository_s_snapshots_carry(
    workspace_root: Path, tmp_path: Path, home: Path, restic: InMemoryRestic
) -> None:
    """Untagged snapshots, from before workspace IDs, are not counted."""
    workspace = _workspace(workspace_root, tmp_path, None)
    restic.snapshots.extend([_days_ago(30), MemorySnapshot(_days_ago(2), OURS, hostname="old")])

    record = _runner_record(workspace, home, restic)

    assert backup_settings(workspace).workspace_id == OURS
    assert record.notice is None
    assert len(restic.workspace_snapshots(OURS)) == 2


def test_snapshots_of_several_workspaces_get_a_new_id_and_say_so(
    workspace_root: Path, tmp_path: Path, home: Path, restic: InMemoryRestic
) -> None:
    workspace = _workspace(workspace_root, tmp_path, None)
    restic.snapshots.extend(
        [MemorySnapshot(_days_ago(2), OURS), MemorySnapshot(_days_ago(1), THEIRS)]
    )

    record = _runner_record(workspace, home, restic)

    chosen = backup_settings(workspace).workspace_id
    assert chosen not in (None, OURS, THEIRS)
    assert record.notice == SEVERAL_WORKSPACES


def test_an_existing_id_is_never_changed(
    workspace_root: Path, tmp_path: Path, home: Path, restic: InMemoryRestic
) -> None:
    workspace = _workspace(workspace_root, tmp_path, OURS)
    restic.snapshots.append(MemorySnapshot(_days_ago(1), THEIRS))
    before = (workspace_root / "settings.yaml").read_bytes()

    record = _runner_record(workspace, home, restic)

    assert (workspace_root / "settings.yaml").read_bytes() == before
    assert record.notice is None
    assert ensure_workspace_id(workspace, restic.snapshot_list(lock=False)) == WorkspaceId(OURS)


def test_an_id_another_writer_saves_first_is_the_one_both_end_with(
    workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(workspace_root, tmp_path, None)
    real_read = workspace_settings.read_settings
    reads = 0

    def read_then_lose_the_race(target: Workspace) -> workspace_settings.SettingsView:
        nonlocal reads
        reads += 1
        current = real_read(target)
        if reads == 1:
            workspace_settings.edit_settings(
                target,
                expected_revision=current.revision,
                changes={workspace_settings.BACKUP_WORKSPACE_ID: THEIRS},
                editable=(workspace_settings.BACKUP_WORKSPACE_ID,),
            )
        return current

    monkeypatch.setattr(workspace_settings, "read_settings", read_then_lose_the_race)

    assert ensure_workspace_id(workspace) == WorkspaceId(THEIRS)
    assert backup_settings(workspace).workspace_id == THEIRS


def _runner_record(workspace: Workspace, home: Path, restic: InMemoryRestic) -> RunRecord:
    runner = BackupRunner(
        workspace, ResticBinaries(home=home), home=home, restic=restic, now=lambda: NOW
    )
    record = runner.run()
    assert record.outcome == "succeeded", record.message
    return record

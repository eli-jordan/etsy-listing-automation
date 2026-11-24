"""A restore through the coordinator against restic itself, every folder in
``tmp_path`` (workspace-backup plan, PR 7 and P3). Skipped unless
``ETSY_LISTINGS_RESTIC_BINARY`` names restic."""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application.backup_coordinator import (
    BackupCoordinator,
    BackupEnvironment,
)
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries

from tests.support.backups import configure_backups, initialise
from tests.support.repository_files import files

pytestmark = pytest.mark.restic


def test_a_restore_writes_the_workspace_back_byte_for_byte(
    restic_binary: Path, workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    workspace = configure_backups(workspace_root, tmp_path / "backups", password=None)
    (workspace_root / "designs").mkdir(exist_ok=True)
    (workspace_root / "designs" / "fox.png").write_bytes(bytes(range(256)) * 512)
    home = tmp_path / "home"
    initialise(workspace, home)
    record = BackupRunner(workspace, ResticBinaries(home=home), home=home).run()
    coordinator = BackupCoordinator(workspace, gate=None, environment=BackupEnvironment(home=home))
    target = tmp_path / "restored"

    coordinator.start_restore(record.snapshot_id or "", target)
    coordinator.join_restore(timeout=60)

    restore = coordinator.overview().restore
    assert restore is not None
    assert restore.outcome == "succeeded", restore.message
    assert files(target) == files(workspace.root)

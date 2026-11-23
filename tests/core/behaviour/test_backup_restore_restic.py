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
from etsy_listings.core.application.backup_repository import create_repository
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.repository_files import files

PASSWORD = "correct horse battery staple"

pytestmark = pytest.mark.restic


def test_a_restore_writes_the_workspace_back_byte_for_byte(
    restic_binary: Path, workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    workspace_root.joinpath("settings.yaml").write_text(
        f"backup:\n  repository: {(tmp_path / 'backups').as_posix()}\n", encoding="utf-8"
    )
    (workspace_root / "designs").mkdir(exist_ok=True)
    (workspace_root / "designs" / "fox.png").write_bytes(bytes(range(256)) * 512)
    workspace = Workspace.discover(root_override=workspace_root)
    home = tmp_path / "home"
    create_repository(workspace, PASSWORD, binaries=ResticBinaries(home=home))
    record = BackupRunner(workspace, ResticBinaries(home=home), home=home).run()
    coordinator = BackupCoordinator(workspace, gate=None, environment=BackupEnvironment(home=home))
    target = tmp_path / "restored"

    coordinator.start_restore(record.snapshot_id or "", target)
    coordinator.join_restore(timeout=60)

    restore = coordinator.overview().restore
    assert restore is not None
    assert restore.outcome == "succeeded", restore.message
    assert files(target) == files(workspace.root)

"""The backup run against restic itself, with every folder in ``tmp_path``
(workspace-backup plan, PR 3 and P3). Skipped unless
``ETSY_LISTINGS_RESTIC_BINARY`` names restic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import create_repository, open_repository
from etsy_listings.core.application.backup_run import BackupRunner, forget_arguments
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.restic import Restic
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.restic import snapshot_path

pytestmark = pytest.mark.restic

PASSWORD = "correct horse battery staple"


@pytest.fixture
def workspace(
    restic_binary: Path, workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Workspace:
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    workspace_root.joinpath("settings.yaml").write_text(
        f"backup:\n  repository: {(tmp_path / 'backups').as_posix()}\n", encoding="utf-8"
    )
    workspace = Workspace.discover(root_override=workspace_root)
    create_repository(workspace, PASSWORD, binaries=ResticBinaries(home=tmp_path / "home"))
    return workspace


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_a_backup_restores_byte_for_byte(workspace: Workspace, tmp_path: Path) -> None:
    designs = workspace.root / "designs"
    designs.mkdir(exist_ok=True)
    (designs / "fox.png").write_bytes(bytes(range(256)) * 512)
    home = tmp_path / "home"
    binaries = ResticBinaries(home=home)

    record = BackupRunner(workspace, binaries, home=home).run()
    target = tmp_path / "restored"
    snapshot_root = snapshot_path(workspace.root)
    open_repository(workspace, binaries=binaries).run(
        "restore", f"latest:{snapshot_root}", "--target", str(target)
    )

    assert record.outcome == "succeeded", record.message
    assert _files(target) == _files(workspace.root)


def _kept_by_the_spec(times: list[datetime]) -> set[datetime]:
    """Every snapshot from the last 7 days, the latest of each of the last 4
    weeks and of the last 3 months, each counted besides the current one
    (spec, *Scope and decisions*, Retention)."""
    latest = max(times)
    kept = {time for time in times if latest - time < timedelta(days=7)}
    weeks = sorted({time.isocalendar()[:2] for time in times}, reverse=True)[:5]
    months = sorted({(time.year, time.month) for time in times}, reverse=True)[:4]
    for week in weeks:
        kept.add(max(time for time in times if time.isocalendar()[:2] == week))
    for month in months:
        kept.add(max(time for time in times if (time.year, time.month) == month))
    return kept


def test_forget_keeps_what_the_retention_describes(restic_binary: Path, tmp_path: Path) -> None:
    restic = Restic(restic_binary, tmp_path / "repository", PASSWORD)
    restic.init()
    source = tmp_path / "source"
    source.mkdir()
    (source / "shop.yaml").write_bytes(b"shop: naturally inked\n")
    start = datetime(2026, 7, 20, 12, tzinfo=UTC)
    times = [start + timedelta(days=6 * n) for n in range(19)]
    times += [datetime(2026, 11, day, 12, tzinfo=UTC) for day in range(13, 22)]
    times.append(datetime(2026, 11, 22, 18, tzinfo=UTC))
    for time in times:
        # Use local calendar dates and let restic apply the host's historical UTC offset.
        local = f"{time:%Y-%m-%d %H:%M:%S}"
        restic.run("backup", str(source), "--host", "test", "--time", local)

    before = [snapshot.time for snapshot in restic.snapshots()]
    assert [time.replace(tzinfo=None) for time in before] == [
        time.replace(tzinfo=None) for time in times
    ]
    restic.run(*forget_arguments(RetentionSettings(keep_within_days=7, weekly=4, monthly=3)))
    remaining = {snapshot.time for snapshot in restic.snapshots()}

    assert remaining == _kept_by_the_spec(before)
    assert len(remaining) < len(set(times))

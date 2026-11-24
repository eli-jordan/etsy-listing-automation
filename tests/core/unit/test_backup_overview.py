"""Each warning the backup status raises (workspace-backup spec, *Status and
warnings*), and that it clears once the problem does: the status is worked
out afresh from the state, the history and restic's snapshots each time, so
there is nothing to dismiss."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_overview import (
    BackupFacts,
    BackupOverview,
    RepositoryReading,
    backup_overview,
    destination_name,
    short_problem,
)
from etsy_listings.core.backup.destinations import ChangedFile
from etsy_listings.core.backup.restic import Snapshot
from etsy_listings.core.backup.state import (
    BackupState,
    CheckResult,
    DestinationState,
    RunRecord,
)
from etsy_listings.core.config.settings import BackupSettings

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
REPOSITORY = Path("/backups")
CLOUD = Path("/cloud/backups")
SETTINGS = BackupSettings(repository=REPOSITORY, destinations=(CLOUD,))


def _snapshot(hours_ago: float) -> Snapshot:
    return Snapshot(
        id="a" * 64,
        short_id="aaaaaaaa",
        time=NOW - timedelta(hours=hours_ago),
        paths=("/workspace",),
        hostname="pc",
    )


def _run(outcome: str, hours_ago: float = 1, message: str | None = None) -> RunRecord:
    at = NOW - timedelta(hours=hours_ago)
    return RunRecord.model_validate(
        {
            "repository": str(REPOSITORY),
            "started_at": at,
            "finished_at": at,
            "outcome": outcome,
            "message": message,
        }
    )


def _copied(hours_ago: float) -> dict[str, DestinationState]:
    return {str(CLOUD): DestinationState(last_copy=NOW - timedelta(hours=hours_ago))}


def _overview(
    *,
    settings: BackupSettings | None = SETTINGS,
    snapshots: tuple[Snapshot, ...] = (_snapshot(1),),
    runs: tuple[RunRecord, ...] = (),
    state: BackupState | None = None,
    missing: bool = False,
) -> BackupOverview:
    return backup_overview(
        BackupFacts(
            settings=settings,
            state=state or BackupState(repository=str(REPOSITORY), destinations=_copied(1)),
            runs=list(runs),
            reading=RepositoryReading(missing=missing, snapshots=None if missing else snapshots),
            running=None,
            now=NOW,
        )
    )


def _kinds(overview: BackupOverview) -> list[str]:
    return [warning.kind for warning in overview.warnings]


def test_a_healthy_backup_raises_no_warning() -> None:
    overview = _overview(runs=(_run("succeeded"),))

    assert overview.warnings == []
    assert overview.last_success == NOW - timedelta(hours=1)
    assert overview.next_due == NOW + timedelta(hours=11)


def test_switched_off_warns_on_the_backup_page_only() -> None:
    (warning,) = _overview(settings=None).warnings

    assert (warning.kind, warning.banner) == ("off", False)


def test_a_missing_repository_warns_naming_its_path() -> None:
    (warning,) = _overview(missing=True).warnings

    assert warning.kind == "repository_missing"
    assert warning.banner
    assert f"Backup repository not found at {REPOSITORY}" in warning.message


def test_a_last_success_more_than_a_day_old_warns_until_a_newer_one() -> None:
    assert _kinds(_overview(snapshots=(_snapshot(25),))) == ["stale"]
    assert _kinds(_overview(snapshots=(_snapshot(25), _snapshot(1)))) == []


def test_a_failed_run_warns_with_restics_message_until_a_run_succeeds() -> None:
    failed = _run("failed", 2, "wrong password: no key found")

    (warning,) = _overview(runs=(failed,)).warnings
    assert warning.kind == "failed"
    assert "wrong password: no key found" in warning.message

    assert _kinds(_overview(runs=(failed, _run("succeeded", 1)))) == []
    assert _kinds(_overview(runs=(_run("stopped", 1),))) == []


def test_a_failed_repository_check_warns_until_a_check_passes() -> None:
    def state(*, ok: bool) -> BackupState:
        check = CheckResult(at=NOW, ok=ok, message=None if ok else "pack a3f9 is damaged")
        return BackupState(repository=str(REPOSITORY), last_check=check, destinations=_copied(1))

    (warning,) = _overview(state=state(ok=False)).warnings
    assert (warning.kind, "pack a3f9 is damaged" in warning.message) == ("failed", True)

    assert _kinds(_overview(state=state(ok=True))) == []


def test_a_destination_more_than_a_day_behind_warns_until_it_catches_up() -> None:
    snapshots = (_snapshot(30), _snapshot(1))

    def state(copied_hours_ago: float) -> BackupState:
        return BackupState(repository=str(REPOSITORY), destinations=_copied(copied_hours_ago))

    (warning,) = _overview(snapshots=snapshots, state=state(40)).warnings
    assert (warning.kind, warning.destination) == ("behind", str(CLOUD))

    # Behind by an hour's snapshot only: not yet a day.
    assert _kinds(_overview(snapshots=snapshots, state=state(20))) == []
    assert _kinds(_overview(snapshots=snapshots, state=state(0.5))) == []
    never = BackupState(repository=str(REPOSITORY))
    assert _kinds(_overview(snapshots=snapshots, state=never)) == ["behind"]


def test_changed_or_unexpected_files_in_a_destination_warn_until_repaired() -> None:
    def state(**found: object) -> BackupState:
        destination = DestinationState(last_copy=NOW, **found)  # type: ignore[arg-type]  # -- the two found-file fields
        return BackupState(repository=str(REPOSITORY), destinations={str(CLOUD): destination})

    changed = state(changed=(ChangedFile("data/7c/7c41", 16_800_000, 16_100_000),))
    unexpected = state(unexpected=("index/a3f9 2",))

    for found in (changed, unexpected):
        (warning,) = _overview(state=found).warnings
        assert (warning.kind, warning.destination, warning.banner) == ("changed", str(CLOUD), True)
    overview = _overview(state=changed)
    assert overview.destinations[0].changed[0].name == "data/7c/7c41"
    today = NOW.astimezone().date().isoformat()
    planned = CLOUD.with_name(f"backups-set-aside-{today}")
    assert overview.destinations[0].set_aside == str(planned)

    assert _kinds(_overview(state=state())) == []
    assert _overview(state=state()).destinations[0].set_aside is None


@pytest.mark.parametrize(
    ("path", "name"),
    [
        (Path("C:/Users/me/iCloudDrive/studio-backups"), "iCloud Drive"),
        (Path("E:/studio-backups"), "studio-backups"),
        (Path("/"), "Folder"),
    ],
)
def test_a_destination_is_named_for_icloud_or_its_folder(path: Path, name: str) -> None:
    assert destination_name(path) == name
    overview = _overview(settings=BackupSettings(repository=REPOSITORY, destinations=(path,)))
    (shown,) = overview.destinations
    assert (shown.name, shown.icloud) == (name, name == "iCloud Drive")


@pytest.mark.parametrize(
    ("problem", "short"),
    [
        ("Folder not found: E:/b. It is caught up once it is back.", "Folder not found"),
        ("Access is denied.", "Access is denied"),
        ("The backup storage folder could not be listed: [WinError 5]", "Not copied"),
        (None, None),
    ],
)
def test_a_copy_problem_is_shortened_for_its_pill(problem: str | None, short: str | None) -> None:
    assert short_problem(problem) == short

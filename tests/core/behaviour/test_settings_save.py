"""The settings save and what it sets off (``settings_save``): the AI-queue
wake, the backup wake, coverage queued for wider position limits, and the
destination folders it refuses or creates. Called directly, against real
files, with recording coordinators in place of the host's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.refusals import (
    InvalidSettingsEditError,
    SettingsRevisionConflictError,
)
from etsy_listings.core.application.settings_save import SettingsCoordinators, save_settings
from etsy_listings.core.render.positions import PositionLimits
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.backups import configure_backups


class _Woken:
    def __init__(self) -> None:
        self.times = 0

    def wake(self) -> None:
        self.times += 1


class _Coverage:
    def __init__(self) -> None:
        self.asked: list[tuple[PositionLimits, PositionLimits]] = []

    def cover_widened(self, saved: PositionLimits, limits: PositionLimits) -> None:
        self.asked.append((saved, limits))


class _Told:
    """Every coordinator a save may tell, recording what it was told."""

    def __init__(self) -> None:
        self.ai_queue = _Woken()
        self.backups = _Woken()
        self.coverage = _Coverage()

    @property
    def coordinators(self) -> SettingsCoordinators:
        return SettingsCoordinators(self.ai_queue, self.backups, self.coverage)

    @property
    def nothing(self) -> bool:
        return (self.ai_queue.times, self.backups.times, self.coverage.asked) == (0, 0, [])


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def told() -> _Told:
    return _Told()


def _save(workspace: Workspace, told: _Told, **changes: object) -> workspace_settings.SettingsView:
    revision = workspace_settings.read_settings(workspace).revision
    return save_settings(
        workspace, expected_revision=revision, changes=changes, coordinators=told.coordinators
    )


def _limits(workspace: Workspace) -> dict[str, object]:
    limits: dict[str, object] = workspace_settings.read_settings(
        workspace
    ).settings.template_positions.model_dump()
    return limits


def test_a_changed_concurrency_wakes_the_ai_queue_and_nothing_else(
    workspace: Workspace, told: _Told
) -> None:
    _save(workspace, told, **{workspace_settings.CONCURRENCY: 3})

    assert (told.ai_queue.times, told.backups.times, told.coverage.asked) == (1, 0, [])


def test_another_key_does_not_wake_the_ai_queue(workspace: Workspace, told: _Told) -> None:
    _save(workspace, told, **{workspace_settings.STEP_LIMIT: 4})

    assert told.nothing


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (workspace_settings.BACKUP_INTERVAL, 6),
        (workspace_settings.BACKUP_RETENTION, {"keep_within_days": 7, "weekly": 8, "monthly": 3}),
        (workspace_settings.BACKUP_DESTINATIONS, []),
    ],
)
def test_any_backup_key_wakes_backups(
    workspace: Workspace, told: _Told, tmp_path: Path, key: str, value: object
) -> None:
    """A shorter interval can make a backup due now."""
    configure_backups(workspace.root, tmp_path / "backups")

    _save(workspace, told, **{key: value})

    assert (told.ai_queue.times, told.backups.times) == (0, 1)


def test_wider_position_limits_queue_coverage_from_the_saved_limits(
    workspace: Workspace, told: _Told
) -> None:
    before = workspace_settings.read_settings(workspace).settings.template_positions
    wider = _limits(workspace) | {"scale": {"min": 0.6, "max": 1.4}}

    view = _save(workspace, told, **{workspace_settings.TEMPLATE_POSITIONS: wider})

    assert told.coverage.asked == [(before, view.settings.template_positions)]
    assert told.ai_queue.times == told.backups.times == 0


def test_narrower_position_limits_queue_nothing(workspace: Workspace, told: _Told) -> None:
    narrower = _limits(workspace) | {"scale": {"min": 0.9, "max": 1.05}}

    _save(workspace, told, **{workspace_settings.TEMPLATE_POSITIONS: narrower})

    assert told.nothing


def test_an_added_destination_is_created_after_the_save(
    workspace: Workspace, told: _Told, tmp_path: Path
) -> None:
    kept = tmp_path / "icloud"
    kept.mkdir()
    added = tmp_path / "usb"
    configure_backups(workspace.root, tmp_path / "backups", destinations=[kept])

    view = _save(
        workspace, told, **{workspace_settings.BACKUP_DESTINATIONS: [str(kept), str(added)]}
    )

    assert added.is_dir()
    assert view.settings.backup is not None
    assert view.settings.backup.destinations == (kept, added)


def test_a_whole_new_block_creates_its_destinations(
    workspace: Workspace, told: _Told, tmp_path: Path
) -> None:
    """Set-up's save goes through the same folder rule."""
    cloud = tmp_path / "cloud"
    block = {"repository": str(tmp_path / "backups"), "destinations": [str(cloud)]}

    save_settings(
        workspace,
        expected_revision=workspace_settings.read_settings(workspace).revision,
        changes={workspace_settings.BACKUP: block},
        editable=(workspace_settings.BACKUP,),
    )

    assert cloud.is_dir()


@pytest.mark.parametrize("problem", ["offline", "file", "overlaps"])
def test_a_destination_it_cannot_create_is_refused_and_nobody_is_told(
    workspace: Workspace, told: _Told, tmp_path: Path, problem: str
) -> None:
    configure_backups(workspace.root, tmp_path / "backups")
    settings = workspace.settings_file().read_bytes()
    a_file = tmp_path / "file"
    a_file.write_bytes(b"keep me")
    offered = {
        "offline": tmp_path / "offline" / "backups",
        "file": a_file,
        "overlaps": workspace.root / "inside",
    }[problem]

    with pytest.raises(InvalidSettingsEditError) as refused:
        _save(workspace, told, **{workspace_settings.BACKUP_DESTINATIONS: [str(offered)]})

    assert workspace_settings.BACKUP_DESTINATIONS in refused.value.field_errors
    assert workspace.settings_file().read_bytes() == settings
    assert a_file.read_bytes() == b"keep me"
    assert not (tmp_path / "offline").exists()
    assert told.nothing


def test_a_stale_save_writes_nothing_and_tells_nobody(
    workspace: Workspace, told: _Told, tmp_path: Path
) -> None:
    added = tmp_path / "usb"
    configure_backups(workspace.root, tmp_path / "backups")
    old = workspace_settings.read_settings(workspace).revision
    with workspace.settings_file().open("a", encoding="utf-8") as settings:
        settings.write("batch_ai:\n  concurrency: 2\n")

    with pytest.raises(SettingsRevisionConflictError):
        save_settings(
            workspace,
            expected_revision=old,
            changes={
                workspace_settings.CONCURRENCY: 3,
                workspace_settings.BACKUP_DESTINATIONS: [str(added)],
            },
            coordinators=told.coordinators,
        )

    assert not added.exists()
    assert told.nothing

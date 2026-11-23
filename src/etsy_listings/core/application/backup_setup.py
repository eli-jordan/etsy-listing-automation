"""Setting backups up from the app, and the destination folders a Setup save
adds (workspace-backup interactions, *Set up and Setup*; plan, PR 5).

A destination folder that does not exist counts as unreachable when a run
copies (spec, *Checking a destination*), so only set-up and a Setup save
create one, and only inside a folder that is there: a missing parent is a
drive, share or sync folder that is offline, refused here with the reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.backup_repository import (
    check_new_repository,
    create_repository,
)
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.restic import Launch
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.errors import ConflictError
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class BackupSetUp:
    """The set-up form's answers."""

    repository: Path
    destinations: tuple[Path, ...]
    interval_hours: int
    retention: RetentionSettings
    password: str


def set_up_backups(
    workspace: Workspace,
    answers: BackupSetUp,
    *,
    expected_revision: str,
    binaries: ResticBinaries,
    launch: Launch | None = None,
) -> workspace_settings.SettingsView:
    """Write the ``backup:`` block, store the password, create the
    repository and the destination folders. Everything that can be refused
    is checked before anything is written; the caller starts the first
    backup."""
    current = workspace_settings.read_settings(workspace)
    if current.settings.backup is not None:
        raise ConflictError("Backups are already set up; change them on the Setup page.")
    check_new_repository(answers.repository, answers.password)
    refuse_unreachable(answers.destinations)
    block = {
        "repository": str(answers.repository),
        "destinations": [str(path) for path in answers.destinations],
        "interval_hours": answers.interval_hours,
        "retention": answers.retention.model_dump(),
    }
    view = workspace_settings.edit_settings(
        workspace,
        expected_revision=expected_revision,
        changes={workspace_settings.BACKUP: block},
        editable=(workspace_settings.BACKUP,),
    )
    create_repository(workspace, answers.password, binaries=binaries, launch=launch)
    create_folders(answers.destinations)
    return view


def added_destinations(workspace: Workspace, changes: Mapping[str, object]) -> tuple[Path, ...]:
    """The destinations a Setup save adds, refused unless each can be
    created. Only checks: :func:`create_folders` runs after the save."""
    edited = changes.get(workspace_settings.BACKUP_DESTINATIONS)
    if not isinstance(edited, Sequence) or isinstance(edited, str):
        return ()
    backup = workspace_settings.read_settings(workspace).settings.backup
    known = set(backup.destinations) if backup is not None else set()
    added = tuple(Path(str(path)) for path in edited if Path(str(path)) not in known)
    refuse_unreachable(added)
    return added


def refuse_unreachable(destinations: Sequence[Path]) -> None:
    missing = [path for path in destinations if not path.is_dir() and not path.parent.is_dir()]
    if missing:
        listed = "; ".join(
            f"{path.parent} does not exist, so {path} cannot be created" for path in missing
        )
        raise InvalidSettingsEditError(
            {
                workspace_settings.BACKUP_DESTINATIONS: f"{listed}. Connect the drive or "
                "sync folder, or choose another folder."
            }
        )


def create_folders(destinations: Sequence[Path]) -> None:
    for path in destinations:
        path.mkdir(exist_ok=True)

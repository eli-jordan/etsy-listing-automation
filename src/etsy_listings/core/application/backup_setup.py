"""Setting backups up from the app, and the destination folders a Setup save
adds (workspace-backup interactions, *Set up and Setup*; plan, PR 5).

A destination folder that does not exist counts as unreachable when a run
copies (spec, *Checking a destination*), so only set-up and a Setup save
create one, and only inside a folder that is there: a missing parent is a
drive, share or sync folder that is offline, refused here with the reason.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.backup_repository import (
    check_backup_paths,
    check_new_storage,
    configured_backup,
    create_repository,
)
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import create_destination
from etsy_listings.core.backup.repository import OpenRepository
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import BackupSettings, RetentionSettings
from etsy_listings.core.errors import ConflictError, RefusedError
from etsy_listings.core.workspace.userpath import to_native_path
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
    restic: OpenRepository | None = None,
) -> workspace_settings.SettingsView:
    """Write the ``backup:`` block, store the password, create the
    repository and the destination folders. Everything that can be refused
    is checked before anything is written; the caller starts the first
    backup."""
    current = workspace_settings.read_settings(workspace)
    if current.settings.backup is not None:
        raise ConflictError("Backups are already set up; change them on the Setup page.")
    check_new_storage(answers.repository, answers.password)
    _refuse_password_override(answers.password)
    # The folders about to be written, refused before they are. The interval
    # is left to the settings save, which refuses it by field.
    folders = BackupSettings(repository=answers.repository, destinations=answers.destinations)
    backup = configured_backup(workspace, folders, binaries=binaries, restic=restic)
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
    create_repository(backup, answers.password)
    create_folders(answers.destinations)
    return view


def _refuse_password_override(password: str) -> None:
    override = os.environ.get(BACKUP_PASSWORD_VAR)
    if override and override != password:
        raise RefusedError(
            f"{BACKUP_PASSWORD_VAR} in the server environment overrides the saved password. "
            "Use the same password here or remove the override and restart the server."
        )


def added_destinations(workspace: Workspace, changes: Mapping[str, object]) -> tuple[Path, ...]:
    """The destinations a Setup save adds, refused unless each can be
    created. Only checks: :func:`create_folders` runs after the save."""
    edited = changes.get(workspace_settings.BACKUP_DESTINATIONS)
    if not isinstance(edited, Sequence) or isinstance(edited, str):
        return ()
    backup = workspace_settings.read_settings(workspace).settings.backup
    known = set(backup.destinations) if backup is not None else set()
    offered = tuple(to_native_path(str(path)) for path in edited)
    storage = None if backup is None else backup.repository
    _refuse_overlapping(workspace, storage, offered)
    added = tuple(path for path in offered if path not in known)
    refuse_unreachable(added)
    return added


def _refuse_overlapping(
    workspace: Workspace, storage: Path | None, paths: tuple[Path, ...]
) -> None:
    if storage is not None and not storage.is_absolute():
        storage = None  # A repository path carried over from another operating system.
    try:
        check_backup_paths(workspace, storage, paths)
    except RefusedError as exc:
        raise InvalidSettingsEditError({workspace_settings.BACKUP_DESTINATIONS: str(exc)}) from exc


def refuse_unreachable(destinations: Sequence[Path]) -> None:
    """``create_destination``'s own refusal, made before anything is
    written, naming the field the form shows it under."""
    for path in destinations:
        _refuse_invalid_folder(path)
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


def _refuse_invalid_folder(path: Path) -> None:
    if not path.is_absolute():
        raise InvalidSettingsEditError(
            {workspace_settings.BACKUP_DESTINATIONS: f"{path} is not a full folder path."}
        )
    if path.exists() and not path.is_dir():
        raise InvalidSettingsEditError(
            {workspace_settings.BACKUP_DESTINATIONS: f"{path} is a file. Choose a folder."}
        )


def create_folders(destinations: Sequence[Path]) -> None:
    """Through the copy's own ``create_destination``, the one place a
    destination folder is made."""
    for path in destinations:
        create_destination(path)

"""Setting backups up from the app, and the destination folders a Setup save
adds (workspace-backup interactions, *Set up and Setup*; plan, PR 5).

A destination folder that does not exist counts as unreachable when a run
copies (spec, *Checking a destination*), so only set-up and a Setup save
create one, and only inside a folder that is there: a missing parent is a
drive, share or sync folder that is offline, refused here with the reason.

**Set-up connects when a destination is already a backup.** A new machine
whose iCloud Drive already holds the backups names that folder as a
destination; set-up then connects the copy there, as Connect does, instead
of creating a repository beside it (``backup_missing.existing_copies``).
:func:`prepare_set_up` refuses everything it can before anything is
written and says which it will do, so the coordinator holds the right slot
for a copy that can take many minutes.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from etsy_listings.core.application import credentials, workspace_settings
from etsy_listings.core.application.backup_missing import (
    Connected,
    ConnectPasswordError,
    connect_existing,
    existing_copies,
)
from etsy_listings.core.application.backup_repository import (
    ConfiguredBackup,
    RepositoryNotEmptyError,
    check_backup_paths,
    check_new_storage,
    configured_backup,
    create_repository,
    holds_files,
    new_workspace_id,
    workspace_id_for,
)
from etsy_listings.core.application.refusals import (
    InvalidSettingsEditError,
    SettingsRevisionConflictError,
)
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import create_destination
from etsy_listings.core.backup.repository import OpenRepository
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import BackupSettings, RetentionSettings
from etsy_listings.core.errors import ConflictError, RefusedError
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.workspace import Workspace

PASSWORD_FIELD = "password"
"""The set-up form's password, as a refusal's field."""


@dataclass(frozen=True)
class BackupSetUp:
    """The set-up form's answers."""

    repository: Path
    destinations: tuple[Path, ...]
    interval_hours: int
    retention: RetentionSettings
    password: str


class ExistingBackupPasswordError(InvalidSettingsEditError):
    """A destination holds a backup the set-up password does not open."""

    def __init__(self, source: Path) -> None:
        message = (
            f"{source} already holds a backup, and this password does not open it. Enter "
            "that backup's password to connect it. Nothing was saved."
        )
        RefusedError.__init__(self, message)
        self.field_errors = {PASSWORD_FIELD: message}


@dataclass(frozen=True)
class PreparedSetUp:
    """Set-up checked and not yet written: :func:`prepare_set_up`'s."""

    workspace: Workspace
    answers: BackupSetUp
    backup: ConfiguredBackup
    copies: tuple[Path, ...]
    """The destinations holding the repository set-up connects, in their
    order; empty when it creates one."""

    @property
    def connects(self) -> bool:
        return bool(self.copies)

    def run(
        self, *, expected_revision: str, trying: Callable[[Path], None] | None = None
    ) -> Connected | None:
        """Connect or create, then save the ``backup:`` block and the
        password and make the destination folders; what was connected, or
        None for a new repository. ``trying`` is told each copy a connect
        tries, before it copies."""
        if not self.connects:
            self._save(expected_revision, new_workspace_id())
            create_repository(self.backup, self.answers.password)
            create_folders(self.answers.destinations)
            return None
        connected = self._connect(expected_revision, trying)
        # Backups are off, so the workspace has no ID: it takes the one the
        # connected snapshots carry, so their schedule carries on (ADR-0060).
        chosen = workspace_id_for(connected.snapshots)
        connected = replace(connected, notice=chosen.notice)
        try:
            self._save(expected_revision, chosen.value)
        except BaseException:
            remove_tree(self.backup.storage)  # The copy just made: nothing is saved.
            raise
        credentials.store(
            self.workspace.root, credentials.BACKUP_PASSWORD, (self.answers.password,)
        )
        create_folders(self.answers.destinations)
        return connected

    def _connect(self, expected_revision: str, trying: Callable[[Path], None] | None) -> Connected:
        if workspace_settings.read_settings(self.workspace).revision != expected_revision:
            raise SettingsRevisionConflictError  # Before a copy that may take minutes.
        tried: list[Path] = []

        def told(source: Path) -> None:
            tried.append(source)
            if trying is not None:
                trying(source)

        try:
            return connect_existing(
                self.backup, self.copies, self.answers.password, env_file=None, trying=told
            )
        except ConnectPasswordError:
            raise ExistingBackupPasswordError(tried[-1]) from None

    def _save(self, expected_revision: str, workspace_id: str) -> None:
        answers = self.answers
        block = {
            "repository": str(answers.repository),
            "destinations": [str(path) for path in answers.destinations],
            "interval_hours": answers.interval_hours,
            "retention": answers.retention.model_dump(),
            "workspace_id": workspace_id,
        }
        workspace_settings.edit_settings(
            self.workspace,
            expected_revision=expected_revision,
            changes={workspace_settings.BACKUP: block},
            editable=(workspace_settings.BACKUP,),
        )


def prepare_set_up(
    workspace: Workspace,
    answers: BackupSetUp,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> PreparedSetUp:
    """Everything set-up can be refused for, checked before anything is
    written, and whether it connects a destination's copy or creates. The
    interval is left to the settings save, which refuses it by field."""
    current = workspace_settings.read_settings(workspace)
    if current.settings.backup is not None:
        raise ConflictError("Backups are already set up; change them on the Setup page.")
    _refuse_password_override(answers.password)
    folders = BackupSettings(repository=answers.repository, destinations=answers.destinations)
    backup = configured_backup(workspace, folders, binaries=binaries, restic=restic)
    refuse_unreachable(answers.destinations)
    copies = existing_copies(answers.destinations)
    if not copies:
        check_new_storage(answers.repository, answers.password)
    elif holds_files(answers.repository):
        raise RepositoryNotEmptyError(
            f"{answers.repository} already holds files. Choose an empty or new folder to "
            "copy the existing backup into."
        )
    elif not answers.password:
        raise ExistingBackupPasswordError(copies[0])
    return PreparedSetUp(workspace, answers, backup, copies)


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

"""Setting backups up from the app, and the destination folders a Setup save
adds (workspace-backup interactions, *Set up and Setup*; plan, PR 5).

A destination folder that does not exist counts as unreachable when a run
copies (spec, *Checking a destination*), so only set-up and a Setup save
create one, and only inside a folder that is there: a missing parent is a
drive, share or sync folder that is offline, refused here with the reason.

**Set-up connects when a destination is already a backup.** A new machine
whose iCloud Drive already holds the backups names that folder as a
destination; set-up then connects the copy there, as Connect does, instead
of creating a repository beside it (``backup_provisioning.source_for``).
:func:`prepare_set_up` refuses what set-up alone refuses and says which it
will do, so the coordinator holds the right slot for a copy that can take
many minutes; ``backup_provisioning`` refuses the rest before it writes,
then provisions the storage folder and saves the whole ``backup:`` block.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.backup_provisioning import (
    BackupsSetUpError,
    Connected,
    ConnectPasswordError,
    DestinationCopy,
    NewBlock,
    PasswordSource,
    Provisioning,
    Source,
    provision,
    source_for,
)
from etsy_listings.core.application.backup_repository import check_backup_paths
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import create_destination
from etsy_listings.core.backup.repository import OpenRepository
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.errors import RefusedError
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
    source: Source
    binaries: ResticBinaries
    restic: OpenRepository | None = None

    @property
    def copies(self) -> tuple[Path, ...]:
        """The destinations holding the repository set-up connects, in their
        order; empty when it creates one."""
        return self.source.copies if isinstance(self.source, DestinationCopy) else ()

    @property
    def connects(self) -> bool:
        return bool(self.copies)

    def run(
        self, *, expected_revision: str, trying: Callable[[Path], None] | None = None
    ) -> Connected | None:
        """Provision the storage folder and save the ``backup:`` block and
        the password, then make the destination folders; what was
        connected, or None for a new repository. ``trying`` is told each
        copy a connect tries, before it copies."""
        answers = self.answers
        asked = Provisioning(
            storage=answers.repository,
            source=self.source,
            password=PasswordSource.typed(answers.password),
            expected_revision=expected_revision,
            new_block=NewBlock(answers.destinations, answers.interval_hours, answers.retention),
        )
        try:
            done = provision(
                self.workspace,
                asked,
                binaries=self.binaries,
                restic=self.restic,
                trying=None if trying is None else _copies_only(trying),
            )
        except ConnectPasswordError as exc:
            # The seller named a destination, not a backup: say which one.
            raise ExistingBackupPasswordError(exc.source) from None
        create_folders(answers.destinations)
        return done.connected


def _copies_only(trying: Callable[[Path], None]) -> Callable[[Path | None], None]:
    def told(source: Path | None) -> None:
        if source is not None:
            trying(source)

    return told


def prepare_set_up(
    workspace: Workspace,
    answers: BackupSetUp,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> PreparedSetUp:
    """What set-up alone refuses, checked before anything is written, and
    whether it connects a destination's copy or creates. The storage folder,
    the password and the interval are ``backup_provisioning``'s to refuse."""
    if workspace_settings.read_settings(workspace).settings.backup is not None:
        raise BackupsSetUpError
    refuse_unreachable(answers.destinations)
    source = source_for(answers.destinations)
    return PreparedSetUp(workspace, answers, source, binaries, restic)


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

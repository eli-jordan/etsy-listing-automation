"""A workspace's configured backup: the facts and folder rules one backup
operation works from, and the repository it opens.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from etsy_listings.core.application import credentials, workspace_settings
from etsy_listings.core.application.refusals import SettingsRevisionConflictError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.repository import OpenRepository, Repository, Snapshot
from etsy_listings.core.backup.restic import Restic
from etsy_listings.core.backup.state import BackupState, BackupStateStore
from etsy_listings.core.config.secrets import Secrets
from etsy_listings.core.config.settings import BackupSettings
from etsy_listings.core.errors import ConflictError, RefusedError, UserFacingError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

MIN_PASSWORD_LENGTH = 12
"""The set-up form's minimum, applied to ``backup init`` too."""


class BackupOffError(ConflictError):
    def __init__(self, settings_file: Path) -> None:
        super().__init__(
            f"Backups are off: {settings_file} has no backup: block. Add one naming "
            "the repository folder (see docs/features/workspace-backup-20261123/spec.md)."
        )


class RepositoryNotEmptyError(ConflictError):
    """restic would put a repository beside the files already there, and a
    later restore or copy would treat them as its own."""


LIVE_WORKSPACE = "That's your live workspace. Choose a new, empty folder."
"""The restore dialog's words (interactions, *Restore*)."""


class RestoreRefusedError(ConflictError): ...


class PasswordTooShortError(RefusedError):
    pass


class ResticNotInstalledError(UserFacingError):
    pass


def inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


def overlaps(first: Path, second: Path) -> bool:
    return inside(first, second) or inside(second, first)


def seller_today(now: datetime) -> date:
    return now.astimezone().date()


def holds_files(folder: Path) -> bool:
    return folder.exists() and (not folder.is_dir() or any(folder.iterdir()))


def has_repository(folder: Path) -> bool:
    """Whether ``folder`` holds restic's ``config``. Runs no restic."""
    return (folder / "config").is_file()


def check_backup_paths(
    workspace: Workspace, repository: Path | None, destinations: Sequence[Path]
) -> None:
    """Keep the backup output outside the workspace and each other."""
    if repository is not None and not repository.is_absolute():
        raise RefusedError(f"{repository} is not a full backup storage folder path.")
    folders = destinations if repository is None else (repository, *destinations)
    separate = [workspace.root, *(path for path in folders if path.is_absolute())]
    for index, folder in enumerate(separate):
        for other in separate[:index]:
            if overlaps(folder, other):
                raise RefusedError(f"{folder} overlaps {other}. Choose separate folders.")


def check_new_storage(folder: Path, password: str) -> None:
    refuse_short_password(password)
    refuse_full_storage(folder)


def refuse_short_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH or not password.strip():
        raise PasswordTooShortError(
            f"The backup password must be at least {MIN_PASSWORD_LENGTH} characters."
        )


def refuse_full_storage(folder: Path) -> None:
    if holds_files(folder):
        raise RepositoryNotEmptyError(
            f"{folder} already holds files. Choose an empty or new folder."
        )


@dataclass(frozen=True)
class ConfiguredBackup:
    workspace: Path
    settings: BackupSettings
    """Its ``repository`` is the storage folder this operation uses."""
    binary: Path | None
    """The restic to run without installing one; None when there is none."""
    store: BackupStateStore
    """The state and run history in ``~/.etsy-listings`` (or a test's home)."""
    secrets: Secrets
    binaries: ResticBinaries
    restic: OpenRepository | None = None

    @property
    def storage(self) -> Path:
        return self.settings.repository

    @property
    def destinations(self) -> tuple[Path, ...]:
        return self.settings.destinations

    @property
    def workspace_id(self) -> str:
        if self.settings.workspace_id is None:
            raise ConflictError(
                f"{self.workspace / layout.SETTINGS_FILE} has no backup.workspace_id. Run "
                "`etsy-listings backup run` or `backup init` to write one."
            )
        return self.settings.workspace_id

    @property
    def password(self) -> str | None:
        return self.secrets.backup_password

    @property
    def env_file(self) -> Path:
        return self.secrets.env_file

    @property
    def present(self) -> bool:
        return has_repository(self.storage)

    def state(self) -> BackupState:
        return self.store.load(self.storage)

    def check_new_storage(self, password: str) -> None:
        check_new_storage(self.storage, password)

    def check_restore_target(self, target: Path, *, now: BackupSettings | None = None) -> Path:
        if not target.is_absolute():
            raise RefusedError(f"{target} is not a full path. Name the folder from its drive.")
        target = target.resolve()
        if target == self.workspace.resolve():
            raise RestoreRefusedError(LIVE_WORKSPACE)
        if inside(target, self.workspace):
            raise RestoreRefusedError(
                f"{target} is inside your live workspace. Choose a new, empty folder outside it."
            )
        if inside(target, self.storage):
            raise RestoreRefusedError(f"{target} is in the backup storage folder. Choose another.")
        if any(inside(target, folder) for folder in self._protected(now)):
            raise RestoreRefusedError(
                f"{target} is in a backup destination. Choose another folder."
            )
        if holds_files(target):
            raise RestoreRefusedError(
                f"{target} already holds files. Choose a new, empty folder, or delete what a "
                "stopped restore left there."
            )
        return target

    def _protected(self, now: BackupSettings | None) -> tuple[Path, ...]:
        if now is None:
            return self.destinations
        return (*self.destinations, now.repository, *now.destinations)

    def open(
        self, *, folder: Path | None = None, password: str | None = None, install: bool = False
    ) -> Repository:
        """The repository in the storage folder, or in ``folder`` (a
        connect's staging copy). ``install`` downloads the pinned restic when
        none is found."""
        password = password or self.secrets.require_backup_password()
        binary = self.binaries.ensure(self.settings.restic_binary) if install else self.binary
        if binary is None:
            raise ResticNotInstalledError(
                "restic is not installed yet. `etsy-listings backup init` downloads the "
                "pinned release, or name one in settings.yaml as backup.restic_binary."
            )
        return repository_at(binary, folder or self.storage, password, restic=self.restic)


def configured_backup(
    workspace: Workspace,
    settings: BackupSettings | None = None,
    *,
    binaries: ResticBinaries,
    home: Path | None = None,
    restic: OpenRepository | None = None,
) -> ConfiguredBackup:
    if settings is None:
        settings = backup_settings(workspace)
    check_backup_paths(workspace, settings.repository, settings.destinations)
    return ConfiguredBackup(
        workspace=workspace.root,
        settings=settings,
        binary=binaries.locate(settings.restic_binary),
        store=BackupStateStore(home),
        secrets=Secrets.load(workspace.root / layout.ENV_FILE),
        binaries=binaries,
        restic=restic,
    )


def backup_settings(workspace: Workspace) -> BackupSettings:
    settings = workspace.capture_settings().backup
    if settings is None:
        raise BackupOffError(workspace.settings_file())
    return settings


def new_workspace_id() -> str:
    return str(uuid.uuid4())


SEVERAL_WORKSPACES = (
    "This backup holds snapshots from more than one workspace, so this workspace "
    "starts its own retention."
)


@dataclass(frozen=True)
class WorkspaceId:
    value: str
    notice: str | None = None
    """Set when the repository's snapshots name several workspaces, so a new
    ID was made instead of adopting one."""


def workspace_id_for(snapshots: Sequence[Snapshot]) -> WorkspaceId:
    found = {snapshot.workspace_id for snapshot in snapshots} - {None}
    if len(found) == 1:
        (only,) = found
        assert only is not None
        return WorkspaceId(only)
    return WorkspaceId(new_workspace_id(), SEVERAL_WORKSPACES if found else None)


def ensure_workspace_id(workspace: Workspace, snapshots: Sequence[Snapshot] = ()) -> WorkspaceId:
    """The workspace ID in ``backup.workspace_id``, writing
    :func:`workspace_id_for` ``snapshots`` there for a block without one."""
    chosen = workspace_id_for(snapshots)
    for _ in range(3):
        current = workspace_settings.read_settings(workspace)
        backup = current.settings.backup
        if backup is None:
            raise BackupOffError(workspace.settings_file())
        if backup.workspace_id is not None:
            return WorkspaceId(backup.workspace_id)
        try:
            workspace_settings.edit_settings(
                workspace,
                expected_revision=current.revision,
                changes={workspace_settings.BACKUP_WORKSPACE_ID: chosen.value},
                editable=(workspace_settings.BACKUP_WORKSPACE_ID,),
            )
        except SettingsRevisionConflictError:
            continue
        return chosen
    raise SettingsRevisionConflictError


def stored_password(workspace: Workspace) -> str | None:
    """The password this machine has, without resolving the configuration."""
    return credentials.stored(workspace.root, credentials.BACKUP_PASSWORD.variables[0])


def create_repository(backup: ConfiguredBackup, password: str) -> str:
    backup.check_new_storage(password)
    return backup.open(password=password, install=True).init()


def repository_at(
    binary: Path, folder: Path, password: str, *, restic: OpenRepository | None = None
) -> Repository:
    return (restic or Restic)(binary, folder, password)


@dataclass(frozen=True)
class BackupStatus:
    settings: BackupSettings | None
    """None when backups are off."""
    binary: Path | None = None
    snapshots: tuple[Snapshot, ...] | None = None
    """Oldest first; None when the repository could not be read."""
    error: UserFacingError | None = None

    @property
    def problem(self) -> str | None:
        return None if self.error is None else str(self.error)


def backup_status(
    workspace: Workspace, *, binaries: ResticBinaries, restic: OpenRepository | None = None
) -> BackupStatus:
    """Takes no repository lock, so it answers while a backup runs."""
    settings = workspace.capture_settings().backup
    if settings is None:
        return BackupStatus(settings=None)
    binary = binaries.locate(settings.restic_binary)
    try:
        backup = configured_backup(workspace, settings, binaries=binaries, restic=restic)
        snapshots = backup.open().snapshots(lock=False)
    except UserFacingError as exc:
        return BackupStatus(settings=settings, binary=binary, error=exc)
    return BackupStatus(settings=settings, binary=binary, snapshots=snapshots)

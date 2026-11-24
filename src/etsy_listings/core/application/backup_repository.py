"""A workspace's backup repository: create it, open it, and report on it.

Joins the three things restic needs: the ``backup:`` block in
``settings.yaml``, the password in the workspace ``.env``, and a restic
binary (workspace-backup spec, *Configuration*; plan, PR 2). The CLI's
``backup init``, ``snapshots`` and ``status`` sit on top; PR 3's backup run
and PR 5's server use the same entry points.

Nothing here downloads restic except :func:`create_repository`, the one
explicit setup step, and nothing creates a repository by itself (spec,
*Missing repository*).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import credentials
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.restic import Launch, Restic, Snapshot
from etsy_listings.core.config.secrets import Secrets
from etsy_listings.core.config.settings import BackupSettings
from etsy_listings.core.errors import ConflictError, RefusedError, UserFacingError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

MIN_PASSWORD_LENGTH = 12
"""The set-up form's minimum (plan, PR 5), applied to ``backup init`` too."""


class BackupOffError(ConflictError):
    def __init__(self, settings_file: Path) -> None:
        super().__init__(
            f"Backups are off: {settings_file} has no backup: block. Add one naming "
            "the repository folder (see docs/features/workspace-backup-20261123/spec.md)."
        )


class RepositoryNotEmptyError(ConflictError):
    """``init`` refuses a folder that already holds files: restic would put a
    repository beside them, and a later restore or copy would treat them as
    part of it."""


class PasswordTooShortError(RefusedError):
    pass


class ResticNotInstalledError(UserFacingError):
    pass


def backup_settings(workspace: Workspace) -> BackupSettings:
    """The ``backup:`` block, or :class:`BackupOffError`."""
    settings = workspace.capture_settings().backup
    if settings is None:
        raise BackupOffError(workspace.settings_file())
    return settings


def stored_password(workspace: Workspace) -> str | None:
    """The password this machine has, the environment first."""
    return credentials.stored(workspace.root, credentials.BACKUP_PASSWORD.variables[0])


def create_repository(
    workspace: Workspace,
    password: str,
    *,
    binaries: ResticBinaries,
    launch: Launch | None = None,
    store: bool = True,
) -> str:
    """Create the configured repository; its restic id.

    ``store`` writes ``password`` into ``.env`` first, before restic runs: a
    repository whose password was never recorded is lost, while a recorded
    password with no repository is only a retry. Installs the pinned restic
    when no other is named.
    """
    settings = backup_settings(workspace)
    check_backup_paths(workspace, settings.repository, settings.destinations)
    check_new_repository(settings.repository, password)
    if store:
        credentials.store(workspace.root, credentials.BACKUP_PASSWORD, (password,))
    binary = binaries.ensure(settings.restic_binary)
    return Restic(binary, settings.repository, password, launch=launch).init()


def check_new_repository(folder: Path, password: str) -> None:
    """Refuse a short password, or a folder that already holds files."""
    if len(password) < MIN_PASSWORD_LENGTH or not password.strip():
        raise PasswordTooShortError(
            f"The backup password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise RepositoryNotEmptyError(
            f"{folder} already holds files. Name an empty or new folder as "
            "backup.repository in settings.yaml."
        )


def paths_overlap(first: Path, second: Path) -> bool:
    first, second = first.resolve(), second.resolve()
    return first.is_relative_to(second) or second.is_relative_to(first)


def check_backup_paths(
    workspace: Workspace, repository: Path | None, destinations: Sequence[Path]
) -> None:
    """Keep the backup output outside the workspace and each other."""
    if repository is not None and not repository.is_absolute():
        raise RefusedError(f"{repository} is not a full backup storage folder path.")
    folders = destinations if repository is None else (repository, *destinations)
    _require_separate([workspace.root, *(path for path in folders if path.is_absolute())])


def _require_separate(folders: list[Path]) -> None:
    for index, folder in enumerate(folders):
        for other in folders[:index]:
            if paths_overlap(folder, other):
                raise RefusedError(f"{folder} overlaps {other}. Choose separate folders.")


def open_repository(
    workspace: Workspace,
    *,
    binaries: ResticBinaries,
    launch: Launch | None = None,
    settings: BackupSettings | None = None,
) -> Restic:
    """The configured repository, ready to run commands. Raises when backups
    are off, the password is missing or no restic is installed; whether the
    repository exists is restic's to say on the first command."""
    settings = settings if settings is not None else backup_settings(workspace)
    password = Secrets.load(workspace.root / layout.ENV_FILE).require_backup_password()
    binary = binaries.locate(settings.restic_binary)
    if binary is None:
        raise ResticNotInstalledError(
            "restic is not installed yet. `etsy-listings backup init` downloads the "
            "pinned release, or name one in settings.yaml as backup.restic_binary."
        )
    return Restic(binary, settings.repository, password, launch=launch)


@dataclass(frozen=True)
class BackupStatus:
    """The configuration and whether the repository opens (plan, PR 2; PR 5
    adds runs, destinations and warnings)."""

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
    workspace: Workspace, *, binaries: ResticBinaries, launch: Launch | None = None
) -> BackupStatus:
    """Read without writing or taking a lock, so it answers while a backup runs."""
    settings = workspace.capture_settings().backup
    if settings is None:
        return BackupStatus(settings=None)
    binary = binaries.locate(settings.restic_binary)
    try:
        snapshots = open_repository(
            workspace, binaries=binaries, launch=launch, settings=settings
        ).snapshots(lock=False)
    except UserFacingError as exc:
        return BackupStatus(settings=settings, binary=binary, error=exc)
    return BackupStatus(settings=settings, binary=binary, snapshots=snapshots)

"""A workspace's configured backup: the facts and folder rules one backup
operation works from, and the repository it opens.

Joins the three things restic needs: the ``backup:`` block in
``settings.yaml``, the password in the workspace ``.env`` (or the
environment), and a restic binary (workspace-backup spec, *Configuration*;
plan, PR 2). :func:`configured_backup` resolves them once per operation into
a :class:`ConfiguredBackup`, refusing a backup storage folder or destination
that overlaps the workspace or another; every run, repair, restore, create,
connect and status read takes that value instead of the settings.

Nothing here downloads restic except an ``install`` open (the one explicit
setup step), and nothing creates a repository by itself (spec, *Missing
repository*).

Every repository the backup opens is opened here, as a
:class:`~etsy_listings.core.backup.repository.Repository`. ``restic``, where
a function takes it, replaces the real restic adapter; tests pass an
in-memory one.

**One "inside" rule.** :func:`inside` resolves both paths and asks
``pathlib``, which on Windows compares case-insensitively by ``str.lower``.
It replaced a second rule the restore used (``os.path.normcase`` and a
string prefix). The two agree on every ordinary path; where they did not,
for letters such as the Kelvin sign that ``str.lower`` folds and Windows'
own mapping keeps, this one calls the folders the same, so it refuses where
the other let a restore through.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import credentials
from etsy_listings.core.application.backup_restore import LIVE_WORKSPACE, RestoreRefusedError
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
"""The set-up form's minimum (plan, PR 5), applied to ``backup init`` too."""


class BackupOffError(ConflictError):
    def __init__(self, settings_file: Path) -> None:
        super().__init__(
            f"Backups are off: {settings_file} has no backup: block. Add one naming "
            "the repository folder (see docs/features/workspace-backup-20261123/spec.md)."
        )


class RepositoryNotEmptyError(ConflictError):
    """A new backup storage folder that already holds files: restic would
    put a repository beside them, and a later restore or copy would treat
    them as part of it."""


class PasswordTooShortError(RefusedError):
    pass


class ResticNotInstalledError(UserFacingError):
    pass


# ------------------------------------------------------------- folder rules


def inside(path: Path, folder: Path) -> bool:
    """Whether ``path`` is ``folder`` or within it, once both are resolved."""
    return path.resolve().is_relative_to(folder.resolve())


def overlaps(first: Path, second: Path) -> bool:
    """Whether either folder is, or is inside, the other."""
    return inside(first, second) or inside(second, first)


def holds_files(folder: Path) -> bool:
    """Whether ``folder`` is a file or a folder with anything in it: what a
    new storage folder, a connect's copy and a restore target must not be."""
    return folder.exists() and (not folder.is_dir() or any(folder.iterdir()))


def has_repository(folder: Path) -> bool:
    """Whether ``folder`` holds restic's ``config``, so a repository is
    present. Runs no restic, so the coordinator asks it on every status read."""
    return (folder / "config").is_file()


def check_backup_paths(
    workspace: Workspace, repository: Path | None, destinations: Sequence[Path]
) -> None:
    """Keep the backup output outside the workspace and each other. A
    relative destination is left to the copy, which reports it unreachable."""
    if repository is not None and not repository.is_absolute():
        raise RefusedError(f"{repository} is not a full backup storage folder path.")
    folders = destinations if repository is None else (repository, *destinations)
    separate = [workspace.root, *(path for path in folders if path.is_absolute())]
    for index, folder in enumerate(separate):
        for other in separate[:index]:
            if overlaps(folder, other):
                raise RefusedError(f"{folder} overlaps {other}. Choose separate folders.")


def check_new_storage(folder: Path, password: str) -> None:
    """Refuse a short password, or a new storage folder that holds files."""
    if len(password) < MIN_PASSWORD_LENGTH or not password.strip():
        raise PasswordTooShortError(
            f"The backup password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if holds_files(folder):
        raise RepositoryNotEmptyError(
            f"{folder} already holds files. Name an empty or new folder as "
            "backup.repository in settings.yaml."
        )


# ---------------------------------------------------- the configured backup


@dataclass(frozen=True)
class ConfiguredBackup:
    """The ``backup:`` block resolved against this machine for one
    operation. Built by :func:`configured_backup`, which has already refused
    overlapping folders. It answers questions about folders and opens the
    repository and the state record; it runs no operation itself."""

    workspace: Path
    """The live workspace's root."""
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
        """The backup storage folder."""
        return self.settings.repository

    @property
    def destinations(self) -> tuple[Path, ...]:
        return self.settings.destinations

    @property
    def password(self) -> str | None:
        """The stored password, the environment first; None when there is none."""
        return self.secrets.backup_password

    @property
    def env_file(self) -> Path:
        return self.secrets.env_file

    @property
    def present(self) -> bool:
        """Whether the storage folder holds a repository."""
        return has_repository(self.storage)

    def state(self) -> BackupState:
        """The storage folder's state record: last prune, check and copies."""
        return self.store.load(self.storage)

    def check_new_storage(self, password: str) -> None:
        """May the storage folder become a new repository with ``password``?
        Its separation was checked when this value was built."""
        check_new_storage(self.storage, password)

    def check_restore_target(self, target: Path, *, now: BackupSettings | None = None) -> Path:
        """``target`` resolved, or refused: not a full path, the live
        workspace or inside it, inside the storage folder or a destination,
        or holding files (spec, *Restore*). ``now`` is the ``backup:`` block
        as it reads just before restic writes; its storage folder and
        destinations are refused as destinations too."""
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
        connect's staging copy), opened with the stored password or
        ``password``. ``install`` downloads the pinned restic when none is
        found; without it, a missing restic is
        :class:`ResticNotInstalledError`. Whether a repository is there is
        restic's to say on the first command."""
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
    """Resolve the configured backup once for an operation.

    ``settings`` is the ``backup:`` block a caller has already read, so an
    operation reads ``settings.yaml`` once; without it the block is read
    here, or :class:`BackupOffError`. Create and connect pass the block
    with the storage folder the seller is about to save. Refuses a storage
    folder that is not a full path, and a storage folder or destination
    that overlaps the workspace or another."""
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
    """The ``backup:`` block, or :class:`BackupOffError`."""
    settings = workspace.capture_settings().backup
    if settings is None:
        raise BackupOffError(workspace.settings_file())
    return settings


def stored_password(workspace: Workspace) -> str | None:
    """The password this machine has, the environment first, read without
    resolving the rest of the configuration."""
    return credentials.stored(workspace.root, credentials.BACKUP_PASSWORD.variables[0])


def create_repository(backup: ConfiguredBackup, password: str, *, store: bool = True) -> str:
    """Create the repository in ``backup``'s storage folder; its restic id.

    ``store`` writes ``password`` into ``.env`` first, before restic runs: a
    repository whose password was never recorded is lost, while a recorded
    password with no repository is only a retry. Installs the pinned restic
    when no other is named.
    """
    backup.check_new_storage(password)
    if store:
        credentials.store(backup.workspace, credentials.BACKUP_PASSWORD, (password,))
    return backup.open(password=password, install=True).init()


def repository_at(
    binary: Path, folder: Path, password: str, *, restic: OpenRepository | None = None
) -> Repository:
    """The repository in ``folder``, run with the restic at ``binary``."""
    return (restic or Restic)(binary, folder, password)


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
    workspace: Workspace, *, binaries: ResticBinaries, restic: OpenRepository | None = None
) -> BackupStatus:
    """Read without writing or taking a lock, so it answers while a backup
    runs. A configuration that would be refused is the problem it reports."""
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

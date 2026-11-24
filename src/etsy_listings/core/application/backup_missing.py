"""The two ways back from a missing repository: create a new one, or
connect an existing one (workspace-backup spec, *Missing repository*;
plan, PR 8).

Both run only while ``backup.repository`` holds no restic repository, and
both take the folder the seller confirms, which becomes
``backup.repository`` when it differs: a workspace restored onto another
machine names a folder from the old one.

**The password.** The one in ``.env`` (or the environment) when there is
one, else the one the seller gives, stored only once the repository is
there. A new repository's must be :data:`MIN_PASSWORD_LENGTH` long; an
existing one's is whatever it was made with.

**Connect copies first.** The chosen repository, typically a destination
copy, is copied with the destinations' own one-way copy into a staging
folder beside the target, so the source is only read and stays a one-way
copy. restic opens the staging copy; only then does it take the target's
name, and only then are ``settings.yaml`` and ``.env`` written. A wrong
password or a failed copy deletes the staging folder and writes nothing.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import credentials, workspace_settings
from etsy_listings.core.application.backup_repository import (
    BackupOffError,
    ConfiguredBackup,
    PasswordTooShortError,
    RepositoryNotEmptyError,
    configured_backup,
    create_repository,
    has_repository,
    holds_files,
    overlaps,
    stored_password,
)
from etsy_listings.core.application.refusals import SettingsRevisionConflictError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import (
    copy_repository,
    holds_repository,
    list_repository,
)
from etsy_listings.core.backup.repository import (
    OpenRepository,
    Repository,
    ResticError,
    WrongPasswordError,
)
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import BackupSettings
from etsy_listings.core.errors import ConflictError, RefusedError
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.workspace import Workspace

STAGING_MARK = ".connecting-"
"""``<target>.connecting-<8 hex>``: where a connect copies before restic
has opened the copy."""


class RepositoryPresentError(ConflictError):
    def __init__(self, repository: Path) -> None:
        super().__init__(
            f"{repository} already holds the backup repository; there is nothing to replace."
        )


class DestinationHoldsRepositoryError(ConflictError):
    """Create refused: a destination still holds a repository's copy, which
    a new repository would leave looking changed (plan, PR 8)."""

    def __init__(self, destination: Path) -> None:
        self.destination = destination
        super().__init__(
            f"{destination} already holds a copy of a backup repository. Use Connect an "
            "existing repository with that folder to keep those backups, or remove that "
            "destination or change it in Setup before creating a new repository."
        )


class ConnectRefusedError(RefusedError):
    """The chosen folder, or its password, does not give a repository."""


class ConnectPasswordError(ConnectRefusedError):
    """The password does not open the copy."""


class ExistingCopiesError(RefusedError):
    """The destinations hold something set-up must not connect or create
    beside: part of a copy, two repositories, or two copies that each lack
    files the other has."""


@dataclass(frozen=True)
class Connected:
    """What set-up connected instead of creating."""

    source: Path
    """The destination it copied from."""
    snapshots: int


@dataclass(frozen=True)
class Replacement:
    """What the seller confirmed for either action."""

    repository: Path
    """The local folder, new or empty; saved as ``backup.repository``."""
    password: str | None
    """Used only when none is stored."""
    expected_revision: str
    """``settings.yaml``'s revision the seller saw."""


def create_new_repository(
    workspace: Workspace,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> None:
    """Create a repository at ``answers.repository``, saving it as the
    backup repository first; refuses a folder that holds files."""
    settings = _missing(workspace, answers.expected_revision)
    for destination in settings.destinations:
        if destination.is_absolute() and holds_repository(destination):
            raise DestinationHoldsRepositoryError(destination)
    backup = _replacing(workspace, settings, answers, binaries=binaries, restic=restic)
    stored = backup.password
    chosen = stored or answers.password
    if not chosen:
        raise PasswordTooShortError("Enter a password for the new backup repository.")
    backup.check_new_storage(chosen)
    _point_at(workspace, settings, answers)
    create_repository(backup, chosen, store=stored is None)


def connect_repository(
    workspace: Workspace,
    source: Path,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> None:
    """Copy the repository at ``source`` into the new folder
    ``answers.repository``, check the password opens it, then save both.
    Writes nothing it is refused for."""
    settings = _missing(workspace, answers.expected_revision)
    stored = stored_password(workspace)
    chosen = stored or answers.password
    if not chosen:
        raise ConnectRefusedError("Enter the password of the repository you are connecting.")
    backup = _replacing(workspace, settings, answers, binaries=binaries, restic=restic)
    _check_connect(workspace, source, answers)
    copy_into_place(
        backup, source, chosen, env_file=backup.env_file if stored is not None else None
    )
    _point_at(workspace, settings, answers)
    if stored is None:
        credentials.store(workspace.root, credentials.BACKUP_PASSWORD, (chosen,))


def copy_into_place(
    backup: ConfiguredBackup, source: Path, password: str, *, env_file: Path | None
) -> int:
    """Copy the repository at ``source`` into a staging folder beside the
    storage folder, open it with ``password`` and check it, then give it the
    storage folder's name; its snapshot count. The storage folder must be
    new or empty. Refused (:class:`ConnectRefusedError`, or
    :class:`ConnectPasswordError` for the password) with nothing left
    behind. ``env_file`` is where ``password`` came from, if it was stored."""
    repository = backup.storage
    staging = repository.with_name(f"{repository.name}{STAGING_MARK}{secrets.token_hex(4)}")
    staging.mkdir()
    try:
        copied = copy_repository(source, staging)
        if copied.outcome != "copied":
            raise ConnectRefusedError(copied.message or f"{source} could not be copied.")
        copy = backup.open(folder=staging, password=password, install=True)
        _open(copy, env_file=env_file)
        snapshots = len(copy.snapshots(lock=False))
        if repository.is_dir():
            repository.rmdir()  # empty: the caller saw to it
        staging.rename(repository)
    finally:
        if staging.exists():
            remove_tree(staging)
    return snapshots


def _missing(workspace: Workspace, expected_revision: str) -> BackupSettings:
    current = workspace_settings.read_settings(workspace)
    if current.revision != expected_revision:
        raise SettingsRevisionConflictError
    settings = current.settings.backup
    if settings is None:
        raise BackupOffError(workspace.settings_file())
    if has_repository(settings.repository):
        raise RepositoryPresentError(settings.repository)
    return settings


def _replacing(
    workspace: Workspace,
    settings: BackupSettings,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None,
) -> ConfiguredBackup:
    """The configured backup with the storage folder the seller confirmed,
    refused if it overlaps the workspace or a destination. The old folder is
    not checked: it may be another machine's path."""
    chosen = settings.model_copy(update={"repository": answers.repository})
    return configured_backup(workspace, chosen, binaries=binaries, restic=restic)


def _check_connect(workspace: Workspace, source: Path, answers: Replacement) -> None:
    """Everything a connect can be refused for before it copies, so a
    20 GB copy is not wasted on a typo."""
    if not has_repository(source):
        raise ConnectRefusedError(
            f"{source} is not a restic repository: it has no config file. Choose the "
            "folder that holds config, data, index, keys and snapshots."
        )
    repository = answers.repository
    if overlaps(repository, source):
        raise ConnectRefusedError("Choose a local folder separate from the source repository.")
    if holds_files(repository):
        raise RepositoryNotEmptyError(
            f"{repository} already holds files. Choose an empty or new folder to copy into."
        )
    if not repository.parent.is_dir():
        raise ConnectRefusedError(f"{repository.parent} does not exist. Choose another folder.")
    if workspace_settings.read_settings(workspace).revision != answers.expected_revision:
        # Checked again by the save itself; this only saves the copy.
        raise SettingsRevisionConflictError


def _open(repository: Repository, *, env_file: Path | None) -> None:
    """Refuse a password that does not open ``repository``, or a copy that
    does not pass a check. A password from ``.env`` is never asked for
    again, so the message says how to change it."""
    try:
        repository.verify_password()
    except WrongPasswordError:
        if env_file is None:
            message = "That password does not open this repository. Nothing was saved."
        else:
            message = (
                f"The password in {env_file} does not open this repository. Nothing was "
                f"saved. Set {BACKUP_PASSWORD_VAR} there (and in the environment, if it is "
                "set) to this repository's password, or delete the line to be asked for "
                "it, then try again."
            )
        raise ConnectPasswordError(message) from None
    except ResticError as exc:
        raise ConnectRefusedError(f"The copied repository did not pass a check: {exc}") from exc
    checked = repository.check()
    if not checked.ok:
        raise ConnectRefusedError(f"The copied repository did not pass a check: {checked.message}")


def _point_at(workspace: Workspace, settings: BackupSettings, answers: Replacement) -> None:
    if answers.repository == settings.repository:
        if workspace_settings.read_settings(workspace).revision != answers.expected_revision:
            raise SettingsRevisionConflictError
        return
    workspace_settings.edit_settings(
        workspace,
        expected_revision=answers.expected_revision,
        changes={workspace_settings.BACKUP_REPOSITORY: str(answers.repository)},
        editable=(workspace_settings.BACKUP_REPOSITORY,),
    )


# ------------------------------------------------------ connecting on set-up


def existing_copies(destinations: Sequence[Path]) -> tuple[Path, ...]:
    """The destinations set-up should connect from, in their order; empty
    when none holds a repository, so set-up creates one.

    Copies of one repository share ``config``'s bytes. A copy whose files
    are all in another (one still syncing) is left out, so the first
    copy-back only adds to it: one that lacked files the other has would
    have them deleted as expired. Refused (:class:`ExistingCopiesError`)
    for part of a copy without ``config``, for two repositories, and for
    copies that each have files the other lacks."""
    listings: dict[Path, dict[str, int]] = {}
    configs: dict[bytes, Path] = {}
    for path in destinations:
        found = _read_copy(path)
        if found is None:
            continue
        config, listings[path] = found
        first = configs.setdefault(config, path)
        if len(configs) > 1:
            raise ExistingCopiesError(
                f"{first} and {path} hold two different backup repositories. Keep only "
                "the destination whose backups you want, then set up again. Nothing was saved."
            )
    return _complete(listings)


def _complete(listings: dict[Path, dict[str, int]]) -> tuple[Path, ...]:
    """The copies holding every file any of the others holds."""
    complete = tuple(
        path
        for path, files in listings.items()
        if all(other.items() <= files.items() for other in listings.values())
    )
    if listings and not complete:
        first, second = list(listings)[:2]
        raise ExistingCopiesError(
            f"{first} and {second} hold copies of the same backup repository, but each has "
            "files the other lacks. Keep only the destination to connect, then set up "
            "again. Nothing was saved."
        )
    return complete


def _read_copy(path: Path) -> tuple[bytes, dict[str, int]] | None:
    """A destination copy's ``config`` bytes and listing; None for a folder
    with none of restic's paths, or one not there yet."""
    if not path.is_absolute() or not path.is_dir() or not holds_repository(path):
        return None
    if not has_repository(path):
        raise ExistingCopiesError(
            f"{path} holds part of a backup repository but no config file, as when a "
            "sync client is still downloading it. Wait until it has finished, or remove "
            "that destination. Nothing was saved."
        )
    try:
        return (path / "config").read_bytes(), list_repository(path)
    except OSError as exc:
        raise ExistingCopiesError(f"{path} could not be read: {exc}") from exc


def connect_existing(
    backup: ConfiguredBackup,
    copies: Sequence[Path],
    password: str,
    *,
    env_file: Path | None,
    trying: Callable[[Path], None] | None = None,
) -> Connected:
    """Connect the first of ``copies`` (from :func:`existing_copies`) that
    ``password`` opens and that passes a check, into ``backup``'s new or
    empty storage folder. A wrong password is refused at once: every copy
    has the same keys. ``trying`` is told each copy before it is copied."""
    if holds_files(backup.storage):
        raise RepositoryNotEmptyError(
            f"{backup.storage} already holds files. Choose an empty or new folder to copy "
            "the existing backup into."
        )
    if not backup.storage.parent.is_dir():
        raise ConnectRefusedError(f"{backup.storage.parent} does not exist. Choose another folder.")
    refused: ConnectRefusedError | None = None
    for source in copies:
        if trying is not None:
            trying(source)
        try:
            snapshots = copy_into_place(backup, source, password, env_file=env_file)
        except ConnectPasswordError:
            raise
        except ConnectRefusedError as exc:
            refused = exc
            continue
        return Connected(source, snapshots)
    if refused is None:
        raise ConnectRefusedError("No destination holds a backup repository to connect.")
    raise refused

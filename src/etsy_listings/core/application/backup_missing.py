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
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import credentials, workspace_settings
from etsy_listings.core.application.backup_repository import (
    BackupOffError,
    PasswordTooShortError,
    RepositoryNotEmptyError,
    check_backup_paths,
    check_new_repository,
    create_repository,
    paths_overlap,
    repository_at,
    stored_password,
)
from etsy_listings.core.application.refusals import SettingsRevisionConflictError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.destinations import copy_repository, holds_repository
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


@dataclass(frozen=True)
class Replacement:
    """What the seller confirmed for either action."""

    repository: Path
    """The local folder, new or empty; saved as ``backup.repository``."""
    password: str | None
    """Used only when none is stored."""
    expected_revision: str
    """``settings.yaml``'s revision the seller saw."""


def has_repository(folder: Path) -> bool:
    """Whether ``folder`` holds restic's ``config``: the coordinator's test
    for a missing repository, which runs no restic."""
    return (folder / "config").is_file()


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
    check_backup_paths(workspace, answers.repository, settings.destinations)
    stored = stored_password(workspace)
    chosen = stored or answers.password
    if not chosen:
        raise PasswordTooShortError("Enter a password for the new backup repository.")
    check_new_repository(answers.repository, chosen)
    _point_at(workspace, settings, answers)
    create_repository(workspace, chosen, binaries=binaries, restic=restic, store=stored is None)


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
    repository = answers.repository
    check_backup_paths(workspace, repository, settings.destinations)
    _check_connect(workspace, source, answers)
    staging = repository.with_name(f"{repository.name}{STAGING_MARK}{secrets.token_hex(4)}")
    staging.mkdir()
    try:
        copied = copy_repository(source, staging)
        if copied.outcome != "copied":
            raise ConnectRefusedError(copied.message or f"{source} could not be copied.")
        copy = repository_at(
            binaries.ensure(settings.restic_binary), staging, chosen, restic=restic
        )
        _open(copy, env_file=workspace.root / ".env" if stored is not None else None)
        if repository.is_dir():
            repository.rmdir()  # empty: _check_connect saw to it
        staging.rename(repository)
    finally:
        if staging.exists():
            remove_tree(staging)
    _point_at(workspace, settings, answers)
    if stored is None:
        credentials.store(workspace.root, credentials.BACKUP_PASSWORD, (chosen,))


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


def _check_connect(workspace: Workspace, source: Path, answers: Replacement) -> None:
    """Everything a connect can be refused for before it copies, so a
    20 GB copy is not wasted on a typo."""
    if not has_repository(source):
        raise ConnectRefusedError(
            f"{source} is not a restic repository: it has no config file. Choose the "
            "folder that holds config, data, index, keys and snapshots."
        )
    repository = answers.repository
    if paths_overlap(repository, source):
        raise ConnectRefusedError("Choose a local folder separate from the source repository.")
    if repository.exists() and (not repository.is_dir() or any(repository.iterdir())):
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
        raise ConnectRefusedError(message) from None
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

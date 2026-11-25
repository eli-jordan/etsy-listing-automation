"""The two ways back from a missing repository: create a new one, or
connect an existing one (workspace-backup spec, *Missing repository*;
plan, PR 8).

Both run only while ``backup.repository`` holds no restic repository, and
both take the folder the seller confirms, which becomes
``backup.repository`` when it differs: a workspace restored onto another
machine names a folder from the old one.

Each says only where the repository comes from and how the password is got;
``backup_provisioning`` does the rest, in its one order, leaving nothing
behind when it is refused or fails. **The password** is the one in ``.env``
(or the environment) when there is one, else the one the seller gives. A
new repository's must be ``MIN_PASSWORD_LENGTH`` long; an existing one's is
whatever it was made with.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.backup_provisioning import (
    DestinationCopy,
    NewRepository,
    PasswordSource,
    Provisioning,
    Source,
    provision,
)
from etsy_listings.core.application.backup_repository import BackupOffError, has_repository
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.repository import OpenRepository
from etsy_listings.core.errors import ConflictError
from etsy_listings.core.workspace.workspace import Workspace


class RepositoryPresentError(ConflictError):
    def __init__(self, repository: Path) -> None:
        super().__init__(
            f"{repository} already holds the backup repository; there is nothing to replace."
        )


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
    """Create a repository at ``answers.repository`` and save it as the
    backup repository; refuses a folder that holds files, and a destination
    that still holds a repository's copy."""
    _replace(workspace, NewRepository(), answers, binaries=binaries, restic=restic)


def connect_repository(
    workspace: Workspace,
    source: Path,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> None:
    """Copy the repository at ``source`` into the new folder
    ``answers.repository``, check the password opens it, then save both."""
    _replace(workspace, DestinationCopy((source,)), answers, binaries=binaries, restic=restic)


def _replace(
    workspace: Workspace,
    source: Source,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None,
) -> None:
    _refuse_unless_missing(workspace)
    asked = Provisioning(
        storage=answers.repository,
        source=source,
        password=PasswordSource.stored_or(lambda _source: answers.password),
        expected_revision=answers.expected_revision,
    )
    provision(workspace, asked, binaries=binaries, restic=restic)


def _refuse_unless_missing(workspace: Workspace) -> None:
    settings = workspace_settings.read_settings(workspace).settings.backup
    if settings is None:
        raise BackupOffError(workspace.settings_file())
    if has_repository(settings.repository):
        raise RepositoryPresentError(settings.repository)

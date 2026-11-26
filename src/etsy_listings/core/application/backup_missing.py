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
    repository: Path
    password: str | None
    """Used only when none is stored."""
    expected_revision: str


def create_new_repository(
    workspace: Workspace,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> None:
    _replace(workspace, NewRepository(), answers, binaries=binaries, restic=restic)


def connect_repository(
    workspace: Workspace,
    source: Path,
    answers: Replacement,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
) -> None:
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

from __future__ import annotations

from collections.abc import Callable
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
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.repository import OpenRepository
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.errors import RefusedError
from etsy_listings.core.workspace.workspace import Workspace

PASSWORD_FIELD = "password"
"""The set-up form's password, as a refusal's field."""


@dataclass(frozen=True)
class BackupSetUp:
    repository: Path
    destinations: tuple[Path, ...]
    interval_hours: int
    retention: RetentionSettings
    password: str


class ExistingBackupPasswordError(InvalidSettingsEditError):
    def __init__(self, source: Path) -> None:
        message = (
            f"{source} already holds a backup, and this password does not open it. Enter "
            "that backup's password to connect it. Nothing was saved."
        )
        RefusedError.__init__(self, message)
        self.field_errors = {PASSWORD_FIELD: message}


@dataclass(frozen=True)
class PreparedSetUp:
    workspace: Workspace
    answers: BackupSetUp
    source: Source
    binaries: ResticBinaries
    restic: OpenRepository | None = None

    @property
    def copies(self) -> tuple[Path, ...]:
        return self.source.copies if isinstance(self.source, DestinationCopy) else ()

    @property
    def connects(self) -> bool:
        return bool(self.copies)

    def run(
        self, *, expected_revision: str, trying: Callable[[Path], None] | None = None
    ) -> Connected | None:
        """Provision the storage folder and save the ``backup:`` block and
        the password; the settings save makes the destination folders. What
        was connected, or None for a new repository. ``trying`` is told each
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
    if workspace_settings.read_settings(workspace).settings.backup is not None:
        raise BackupsSetUpError
    source = source_for(answers.destinations)
    return PreparedSetUp(workspace, answers, source, binaries, restic)

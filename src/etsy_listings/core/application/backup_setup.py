"""Setting backups up from the app (workspace-backup interactions, *Set up
and Setup*; plan, PR 5). Which destination folders a save may create, and
when they are made, is ``settings_save``'s.

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
    """Whether set-up connects a destination's copy or creates, refused
    while backups are set up. The storage folder, the password, the
    destinations and the interval are refused by ``backup_provisioning`` and
    the settings save it ends with, before anything is written."""
    if workspace_settings.read_settings(workspace).settings.backup is not None:
        raise BackupsSetUpError
    source = source_for(answers.destinations)
    return PreparedSetUp(workspace, answers, source, binaries, restic)

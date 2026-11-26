"""Provisioning the backup storage folder: bringing a restic repository into
it, new or copied from a Destination, and saving the ``backup:`` block that
names it (workspace-backup spec, *Set-up* and *Missing repository*;
ADR-0060, ADR-0061).

Every entry point goes through :func:`provision`, which refuses first and
undoes on failure (architecture, *restic for workspace backup*).
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NamedTuple

from etsy_listings.core.application import credentials, settings_save, workspace_settings
from etsy_listings.core.application.backup_repository import (
    BackupOffError,
    ConfiguredBackup,
    PasswordTooShortError,
    WorkspaceId,
    configured_backup,
    create_repository,
    has_repository,
    overlaps,
    refuse_full_storage,
    refuse_short_password,
    stored_password,
    workspace_id_for,
)
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
    Snapshot,
    WrongPasswordError,
)
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import BackupSettings, RetentionSettings
from etsy_listings.core.errors import ConflictError, RefusedError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.atomic import write_bytes_atomic
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

STAGING_MARK = ".provisioning-"
"""``<storage>.provisioning-<8 hex>``: where a repository is built or
copied before it takes the storage folder's name."""


class BackupsSetUpError(ConflictError):
    def __init__(self) -> None:
        super().__init__("Backups are already set up; change them on the Setup page.")


class DestinationHoldsRepositoryError(ConflictError):
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        super().__init__(
            f"{destination} already holds a copy of a backup repository. Use Connect an "
            "existing repository with that folder to keep those backups, or remove that "
            "destination or change it in Setup before creating a new repository."
        )


class ConnectRefusedError(RefusedError): ...


class ConnectPasswordError(ConnectRefusedError):
    def __init__(self, message: str, source: Path) -> None:
        super().__init__(message)
        self.source = source


class ExistingCopiesError(RefusedError): ...


@dataclass(frozen=True)
class NewRepository: ...


@dataclass(frozen=True)
class DestinationCopy:
    """Copy in the first of ``copies`` the password opens and that passes a
    check."""

    copies: tuple[Path, ...]


Source = NewRepository | DestinationCopy


@dataclass(frozen=True)
class PasswordSource:
    """How an entry point gets the password; ``ask`` is told where the
    repository comes from."""

    ask: Callable[[Source], str | None]
    replaces_stored: bool = False
    """True for a password the seller has just typed for this set-up: used
    and stored even over one in ``.env``, and refused while the environment
    overrides it. False uses the stored password and asks only without one."""

    @classmethod
    def typed(cls, password: str) -> PasswordSource:
        return cls(lambda _source: password, replaces_stored=True)

    @classmethod
    def stored_or(cls, ask: Callable[[Source], str | None]) -> PasswordSource:
        return cls(ask)


@dataclass(frozen=True)
class NewBlock:
    """Set-up's ``backup:`` block, less the storage folder and workspace ID
    :func:`provision` adds."""

    destinations: tuple[Path, ...]
    interval_hours: int
    retention: RetentionSettings


@dataclass(frozen=True)
class Connected:
    source: Path
    """The copy it was copied from."""
    snapshots: tuple[Snapshot, ...]
    """The copy's snapshots, read without the lock."""
    notice: str | None = None
    """What to say beside it, such as a new workspace ID among several."""


@dataclass(frozen=True)
class Provisioned:
    connected: Connected | None
    """None for a new repository."""
    repository_id: str | None
    """A new repository's restic id; None for a copy."""
    workspace_id: WorkspaceId
    stored_password: bool
    """Whether this attempt wrote the password into ``.env``."""


def source_for(destinations: Sequence[Path]) -> Source:
    copies = existing_copies(destinations)
    return DestinationCopy(copies) if copies else NewRepository()


@dataclass(frozen=True)
class Provisioning:
    storage: Path
    """The backup storage folder: new, or an empty folder."""
    source: Source
    password: PasswordSource
    expected_revision: str | None = None
    """The ``settings.yaml`` revision the seller saw; None takes it as it
    reads now, for a caller no page read it for."""
    new_block: NewBlock | None = None
    """Set-up's whole block, refused while one is saved. Without it the
    saved block is kept, its ``repository`` set to :attr:`storage` when that
    differs, and its workspace ID added when it has none."""


def provision(
    workspace: Workspace,
    asked: Provisioning,
    *,
    binaries: ResticBinaries,
    restic: OpenRepository | None = None,
    trying: Callable[[Path | None], None] | None = None,
) -> Provisioned:
    """Provision ``asked.storage`` from ``asked.source``. ``trying`` is told
    each copy before it is copied, or None before a new repository is made."""
    plan = _plan(workspace, asked, binaries, restic)
    password = _password(workspace, asked.source, asked.password)
    storage = asked.storage
    with ExitStack() as undo:
        if not password.already_stored:
            _store(workspace, password.value, undo)
        undo.callback(_quietly, _take_back, storage, existed=storage.is_dir())
        brought = _bring(
            plan.backup,
            asked.source,
            password.value,
            stored=password.already_stored,
            trying=trying,
        )
        workspace_id = plan.workspace_id(
            brought.snapshots if isinstance(brought, Connected) else ()
        )
        plan.save(workspace_id.value)
        undo.pop_all()
    stored_password = not password.already_stored
    if isinstance(brought, _Created):
        return Provisioned(None, brought.repository_id, workspace_id, stored_password)
    connected = replace(brought, notice=workspace_id.notice)
    return Provisioned(connected, None, workspace_id, stored_password)


@dataclass(frozen=True)
class _Plan:
    workspace: Workspace
    backup: ConfiguredBackup
    saved: BackupSettings | None
    new_block: NewBlock | None
    expected_revision: str

    def workspace_id(self, snapshots: Sequence[Snapshot]) -> WorkspaceId:
        if self.saved is not None and self.saved.workspace_id is not None:
            return WorkspaceId(self.saved.workspace_id)
        return workspace_id_for(snapshots)

    def changes(self, workspace_id: str) -> tuple[dict[str, object], tuple[str, ...]]:
        storage = self.backup.storage
        if self.new_block is not None:
            block = {
                "repository": str(storage),
                "destinations": [str(path) for path in self.new_block.destinations],
                "interval_hours": self.new_block.interval_hours,
                "retention": self.new_block.retention.model_dump(),
                "workspace_id": workspace_id,
            }
            return {workspace_settings.BACKUP: block}, (workspace_settings.BACKUP,)
        assert self.saved is not None
        changes: dict[str, object] = {}
        if storage != self.saved.repository:
            changes[workspace_settings.BACKUP_REPOSITORY] = str(storage)
        if self.saved.workspace_id is None:
            changes[workspace_settings.BACKUP_WORKSPACE_ID] = workspace_id
        return changes, tuple(changes)

    def check(self) -> None:
        changes, editable = self.changes(self.workspace_id(()).value)
        settings_save.check_settings_save(
            self.workspace,
            expected_revision=self.expected_revision,
            changes=changes,
            editable=editable,
        )

    def save(self, workspace_id: str) -> None:
        changes, editable = self.changes(workspace_id)
        settings_save.save_settings(
            self.workspace,
            expected_revision=self.expected_revision,
            changes=changes,
            editable=editable,
        )


def _plan(
    workspace: Workspace,
    asked: Provisioning,
    binaries: ResticBinaries,
    restic: OpenRepository | None,
) -> _Plan:
    current = workspace_settings.read_settings(workspace)
    saved, new_block = current.settings.backup, asked.new_block
    if new_block is not None and saved is not None:
        raise BackupsSetUpError
    if saved is not None:
        folders = saved.model_copy(update={"repository": asked.storage})
    elif new_block is not None:
        folders = BackupSettings(repository=asked.storage, destinations=new_block.destinations)
    else:
        raise BackupOffError(workspace.settings_file())
    backup = configured_backup(workspace, folders, binaries=binaries, restic=restic)
    _refuse_storage(asked.storage)
    _refuse_source(asked.source, asked.storage, backup.destinations)
    revision = current.revision if asked.expected_revision is None else asked.expected_revision
    plan = _Plan(workspace, backup, saved, new_block, revision)
    plan.check()
    return plan


def _refuse_storage(storage: Path) -> None:
    refuse_full_storage(storage)
    if not storage.parent.is_dir():
        raise RefusedError(f"{storage.parent} does not exist. Choose another folder.")


def _refuse_source(source: Source, storage: Path, destinations: Sequence[Path]) -> None:
    if isinstance(source, NewRepository):
        _refuse_beside_a_copy(destinations)
        return
    if not source.copies:
        raise ConnectRefusedError("No destination holds a backup repository to connect.")
    for copy in source.copies:
        _refuse_copy(copy, storage)


def _refuse_beside_a_copy(destinations: Sequence[Path]) -> None:
    for destination in destinations:
        if destination.is_absolute() and holds_repository(destination):
            raise DestinationHoldsRepositoryError(destination)


def _refuse_copy(copy: Path, storage: Path) -> None:
    if not has_repository(copy):
        raise ConnectRefusedError(
            f"{copy} is not a restic repository: it has no config file. Choose the "
            "folder that holds config, data, index, keys and snapshots."
        )
    if overlaps(storage, copy):
        raise ConnectRefusedError("Choose a local folder separate from the source repository.")


class _Password(NamedTuple):
    value: str
    already_stored: bool


def _password(workspace: Workspace, source: Source, supply: PasswordSource) -> _Password:
    stored = None if supply.replaces_stored else stored_password(workspace)
    chosen = stored or supply.ask(source) or ""
    if supply.replaces_stored:
        _refuse_override(chosen)
    if isinstance(source, NewRepository):
        if not chosen:
            raise PasswordTooShortError("Enter a password for the new backup repository.")
        refuse_short_password(chosen)
    elif not chosen:
        raise ConnectPasswordError(
            "Enter the password of the repository you are connecting.", source.copies[0]
        )
    return _Password(chosen, already_stored=stored is not None)


def _refuse_override(password: str) -> None:
    override = os.environ.get(BACKUP_PASSWORD_VAR)
    if override and override != password:
        raise RefusedError(
            f"{BACKUP_PASSWORD_VAR} in the server environment overrides the saved password. "
            "Use the same password here or remove the override and restart the server."
        )


def _store(workspace: Workspace, password: str, undo: ExitStack) -> None:
    env = workspace.root / layout.ENV_FILE
    before = env.read_bytes() if env.is_file() else None
    credentials.store(workspace.root, credentials.BACKUP_PASSWORD, (password,))
    undo.callback(_quietly, _put_back, env, before)


def _put_back(env: Path, before: bytes | None) -> None:
    if before is None:
        env.unlink(missing_ok=True)
    else:
        write_bytes_atomic(env, before, durable=True)


def _take_back(storage: Path, *, existed: bool) -> None:
    """Remove a repository this attempt put in ``storage``: safe, because
    the folder was new or empty."""
    if has_repository(storage):
        remove_tree(storage)
    if existed and not storage.exists():
        storage.mkdir()


def _quietly(undo: Callable[..., None], *args: object, **kwargs: object) -> None:
    """Run one undo, logging rather than raising over the failure it undoes."""
    try:
        undo(*args, **kwargs)
    except Exception:
        logger.exception("undoing part of a failed backup provisioning failed")


@dataclass(frozen=True)
class _Created:
    repository_id: str


def _bring(
    backup: ConfiguredBackup,
    source: Source,
    password: str,
    *,
    stored: bool,
    trying: Callable[[Path | None], None] | None,
) -> Connected | _Created:
    told = trying or (lambda _source: None)
    if isinstance(source, NewRepository):
        told(None)
        return _Created(_into_place(backup.storage, _initialised(backup, password)))
    env_file = backup.env_file if stored else None

    def connect(copy: Path) -> Connected:
        told(copy)
        return Connected(
            copy, _into_place(backup.storage, _copied(backup, copy, password, env_file))
        )

    *earlier, last = source.copies
    for copy in earlier:
        try:
            return connect(copy)
        except ConnectPasswordError:
            raise
        except ConnectRefusedError:
            continue
    return connect(last)


def _into_place[T](storage: Path, bring: Callable[[Path], T]) -> T:
    staging = storage.with_name(f"{storage.name}{STAGING_MARK}{secrets.token_hex(4)}")
    staging.mkdir()
    try:
        brought = bring(staging)
        if storage.is_dir():
            storage.rmdir()  # empty: refused otherwise
        staging.rename(storage)
    finally:
        if staging.exists():
            remove_tree(staging)
    return brought


def _initialised(backup: ConfiguredBackup, password: str) -> Callable[[Path], str]:
    def bring(staging: Path) -> str:
        settings = backup.settings.model_copy(update={"repository": staging})
        return create_repository(replace(backup, settings=settings), password)

    return bring


def _copied(
    backup: ConfiguredBackup, source: Path, password: str, env_file: Path | None
) -> Callable[[Path], tuple[Snapshot, ...]]:
    def bring(staging: Path) -> tuple[Snapshot, ...]:
        copied = copy_repository(source, staging)
        if copied.outcome != "copied":
            raise ConnectRefusedError(copied.message or f"{source} could not be copied.")
        copy = backup.open(folder=staging, password=password, install=True)
        _open(copy, source, env_file=env_file)
        return copy.snapshots(lock=False)

    return bring


def _open(repository: Repository, source: Path, *, env_file: Path | None) -> None:
    """Refuse a password that does not open ``repository``, or a copy that
    does not pass a check."""
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
        raise ConnectPasswordError(message, source) from None
    except ResticError as exc:
        raise ConnectRefusedError(f"The copied repository did not pass a check: {exc}") from exc
    checked = repository.check()
    if not checked.ok:
        raise ConnectRefusedError(f"The copied repository did not pass a check: {checked.message}")


def existing_copies(destinations: Sequence[Path]) -> tuple[Path, ...]:
    """The destinations set-up should connect from, in their order; empty
    when none holds a repository."""
    listings: dict[Path, Mapping[str, int]] = {}
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


def _complete(listings: Mapping[Path, Mapping[str, int]]) -> tuple[Path, ...]:
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

"""Provisioning the backup storage folder: bringing a restic repository into
it, new or copied from a Destination, and saving the ``backup:`` block that
names it (workspace-backup spec, *Set-up* and *Missing repository*;
ADR-0060, ADR-0061).

Four entry points provision: Setup (``backup_setup``), the missing banner's
Create and Connect (``backup_missing``) and ``etsy-listings backup init``.
Each says only where the repository comes from (:class:`NewRepository`, or
a :class:`DestinationCopy`) and how the password is got
(:class:`PasswordSource`). :func:`provision` is the module's whole
interface: it runs every step in one order and owns the clean-up, so a rule
about provisioning lands here once rather than in four sequences.

**The order.**

1. Refuse, writing nothing: backups off (or already set up, for a new
   block); a storage folder that overlaps the workspace or a destination,
   that already holds files, or whose parent folder is missing; a new
   repository while a destination still holds a repository's copy; a copy
   that is not a restic repository or overlaps the storage folder; and the
   ``backup:`` save itself, checked against the revision and validated
   without writing.
2. Get the password, only now, so a terminal never prompts for an attempt
   that is refused anyway, and refuse a missing or short one.
3. Store it in ``.env``, when this attempt brings it.
4. Bring the repository into a staging folder beside the storage folder
   (``restic init``, or the destinations' one-way copy, then open and
   check it), then give it the storage folder's name.
5. Choose the workspace ID: the block's own when it has one, else the one
   the repository's snapshots carry, else a new one (ADR-0061).
6. Save the ``backup:`` block, revision-checked.

**Why this order: failure leaves nothing behind.** Any failure in steps 3
to 6, a refusal or a crash of restic alike, leaves the workspace as it was
before the attempt: no stored password, no saved block, no repository and
no staging folder. Each written step registers its undo, and a failure
runs them in reverse.

- The password is stored before any repository exists, so even a process
  killed part way never leaves a repository on this disk whose password
  this machine did not record. Killed there, it leaves at most the
  password, which is only a retry; a failure the process sees puts ``.env``
  back byte for byte.
- The repository is built in staging and renamed whole, so the storage
  folder is never half a repository, and the undo removes only a folder
  holding restic's ``config`` (remaking the empty folder the seller named,
  if there was one).
- The block is saved last, as the commit point: once it names the folder,
  the schedule may back up into it, so the folder must already hold a
  complete, checked repository. Step 1 checked the same save beforehand,
  so a stale page or an invalid interval is refused before a copy that can
  take many minutes; the save checks the revision again.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path

from etsy_listings.core.application import credentials, workspace_settings
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


# ------------------------------------------------------------------ refusals


class BackupsSetUpError(ConflictError):
    def __init__(self) -> None:
        super().__init__("Backups are already set up; change them on the Setup page.")


class DestinationHoldsRepositoryError(ConflictError):
    """A new repository refused: a destination still holds a repository's
    copy, which a new repository would leave looking changed (plan, PR 8)."""

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
    """The password is missing or does not open the copy at ``source``."""

    def __init__(self, message: str, source: Path) -> None:
        super().__init__(message)
        self.source = source


class ExistingCopiesError(RefusedError):
    """The destinations hold something set-up must not connect or create
    beside: part of a copy, two repositories, or two copies that each lack
    files the other has."""


# ------------------------------------------------- what an entry point says


@dataclass(frozen=True)
class NewRepository:
    """``restic init`` a new, empty repository."""


@dataclass(frozen=True)
class DestinationCopy:
    """Copy an existing repository in: the first of ``copies`` the password
    opens and that passes a check. Usually destinations; Connect names any
    folder holding a copy."""

    copies: tuple[Path, ...]


Source = NewRepository | DestinationCopy


@dataclass(frozen=True)
class PasswordSource:
    """How an entry point gets the password. ``ask`` is called once every
    refusal that needs no password has passed, and told where the repository
    comes from; a None or blank answer is refused."""

    ask: Callable[[Source], str | None]
    replaces_stored: bool = False
    """True for a password the seller has just typed for this set-up: used
    and stored even over one in ``.env``, and refused while the environment
    overrides it. False uses the stored password and asks only without one."""

    @classmethod
    def typed(cls, password: str) -> PasswordSource:
        """Setup's: the form's password."""
        return cls(lambda _source: password, replaces_stored=True)

    @classmethod
    def stored_or(cls, ask: Callable[[Source], str | None]) -> PasswordSource:
        """The stored password, else ``ask``'s, stored once it is used."""
        return cls(ask)


@dataclass(frozen=True)
class NewBlock:
    """Set-up's ``backup:`` block, written whole; the storage folder and
    the workspace ID come from :func:`provision`."""

    destinations: tuple[Path, ...]
    interval_hours: int
    retention: RetentionSettings


# --------------------------------------------------------------- the answer


@dataclass(frozen=True)
class Connected:
    """What was connected instead of created."""

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
    """Set-up's and ``backup init``'s choice: a destination's copy when one
    holds a repository (:func:`existing_copies`), else a new repository."""
    copies = existing_copies(destinations)
    return DestinationCopy(copies) if copies else NewRepository()


@dataclass(frozen=True)
class Provisioning:
    """What an entry point asks for: which folder, from where, with which
    password, and the block to save."""

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
    """Provision ``asked.storage`` from ``asked.source``, in the order the
    module docstring gives, leaving nothing behind on failure. ``trying`` is
    told each copy before it is copied, or None before a new repository is
    made."""
    plan = _plan(workspace, asked, binaries, restic)
    chosen, stored = _password(workspace, asked.source, asked.password)
    storage = asked.storage
    with ExitStack() as undo:
        if not stored:
            _store(workspace, chosen, undo)
        undo.callback(_quietly, _take_back, storage, existed=storage.is_dir())
        connected, repository_id = _bring(
            plan.backup, asked.source, chosen, stored=stored, trying=trying
        )
        workspace_id = plan.workspace_id(() if connected is None else connected.snapshots)
        plan.save(workspace_id.value)
        undo.pop_all()
    if connected is not None:
        connected = replace(connected, notice=workspace_id.notice)
    return Provisioned(connected, repository_id, workspace_id, stored_password=not stored)


# ------------------------------------------------------------ 1. refusals


@dataclass(frozen=True)
class _Plan:
    workspace: Workspace
    backup: ConfiguredBackup
    saved: BackupSettings | None
    new_block: NewBlock | None
    expected_revision: str

    def workspace_id(self, snapshots: Sequence[Snapshot]) -> WorkspaceId:
        """The saved block's ID, kept; else the one ``snapshots`` carry."""
        if self.saved is not None and self.saved.workspace_id is not None:
            return WorkspaceId(self.saved.workspace_id)
        return workspace_id_for(snapshots)

    def changes(self, workspace_id: str) -> tuple[dict[str, object], tuple[str, ...]]:
        """The settings edit that saves the block, and the keys it may change."""
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
        """The save refused now, as it would be at the end."""
        changes, editable = self.changes(self.workspace_id(()).value)
        workspace_settings.check_settings_edit(
            self.workspace,
            expected_revision=self.expected_revision,
            changes=changes,
            editable=editable,
        )

    def save(self, workspace_id: str) -> None:
        changes, editable = self.changes(workspace_id)
        workspace_settings.edit_settings(
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


# ----------------------------------------------------------- 2. password


def _password(workspace: Workspace, source: Source, supply: PasswordSource) -> tuple[str, bool]:
    """The password, and whether it is already stored."""
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
    return chosen, stored is not None


def _refuse_override(password: str) -> None:
    override = os.environ.get(BACKUP_PASSWORD_VAR)
    if override and override != password:
        raise RefusedError(
            f"{BACKUP_PASSWORD_VAR} in the server environment overrides the saved password. "
            "Use the same password here or remove the override and restart the server."
        )


# ------------------------------------------------------------ 3. storing


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
    """Remove a repository this attempt put in ``storage``; the folder was
    new or empty, so nothing of the seller's is in it."""
    if has_repository(storage):
        remove_tree(storage)
    if existed and not storage.exists():
        storage.mkdir()


def _quietly(undo: Callable[..., None], *args: object, **kwargs: object) -> None:
    """Run one undo; its own failure is logged, not raised over the failure
    being undone."""
    try:
        undo(*args, **kwargs)
    except Exception:
        logger.exception("undoing part of a failed backup provisioning failed")


# ----------------------------------------------------------- 4. bringing


def _bring(
    backup: ConfiguredBackup,
    source: Source,
    password: str,
    *,
    stored: bool,
    trying: Callable[[Path | None], None] | None,
) -> tuple[Connected | None, str | None]:
    """The repository in the storage folder: what was connected, or the new
    repository's id."""
    told = trying or (lambda _source: None)
    if isinstance(source, NewRepository):
        told(None)
        return None, _into_place(backup.storage, _initialised(backup, password))
    env_file = backup.env_file if stored else None
    refused: ConnectRefusedError | None = None
    for copy in source.copies:
        told(copy)
        try:
            snapshots = _into_place(backup.storage, _copied(backup, copy, password, env_file))
        except ConnectPasswordError:
            raise  # Every copy has the same keys.
        except ConnectRefusedError as exc:
            refused = exc
            continue
        return Connected(copy, snapshots), None
    assert refused is not None  # _refuse_source refused no copies.
    raise refused


def _into_place[T](storage: Path, bring: Callable[[Path], T]) -> T:
    """``bring`` a repository into a new staging folder beside ``storage``,
    then give it ``storage``'s name; the staging folder never outlives it."""
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
        return create_repository(replace(backup, settings=settings), password, store=False)

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
        raise ConnectPasswordError(message, source) from None
    except ResticError as exc:
        raise ConnectRefusedError(f"The copied repository did not pass a check: {exc}") from exc
    checked = repository.check()
    if not checked.ok:
        raise ConnectRefusedError(f"The copied repository did not pass a check: {checked.message}")


# ------------------------------------------- which destination to connect


def existing_copies(destinations: Sequence[Path]) -> tuple[Path, ...]:
    """The destinations set-up should connect from, in their order; empty
    when none holds a repository, so set-up creates one.

    Copies of one repository share ``config``'s bytes. A copy whose files
    are all in another (one still syncing) is left out, so the first
    copy-back only adds to it: one that lacked files the other has would
    have them deleted as expired. Refused (:class:`ExistingCopiesError`)
    for part of a copy without ``config``, for two repositories, and for
    copies that each have files the other lacks."""
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

"""The settings save: a revision-checked ``settings.yaml`` edit and what it
sets off (Admin plan, PR 4; ADR-0048, ADR-0052, ADR-0058).

``workspace_settings`` reads, checks and writes the file. This module is
the save every owner of a settings change goes through, the Admin page's
``PATCH`` and backup provisioning alike, and it decides what the change sets
off, so no caller repeats a rule:

- **Destinations.** A ``backup.destinations`` the save adds, or each one a
  whole new ``backup:`` block names, is refused unless it can be created
  (its parent folder exists, it is not a file, it overlaps nothing), and is
  created after the write. A destination folder that does not exist counts
  as unreachable when a run copies (spec, *Checking a destination*), so
  only a save makes one, and only inside a folder that is there: a missing
  parent is a drive, share or sync folder that is offline.
- **The AI queue** is woken when ``batch_ai.concurrency`` changes, as the
  queue reads it afresh on its next dispatch (ADR-0048). Waking never stops
  runs already going when the limit was lowered.
- **Backups** are woken when any backup key changes: a shorter interval can
  make a backup due now.
- **Position coverage** is queued when the template position limits widen
  (option B, ADR-0058); narrowing queues nothing.

**The coordinators** are handed in (:class:`SettingsCoordinators`); the
host builds them and keeps owning their lifetimes (ADR-0052). One left out
is not told: backup provisioning passes none, because the backup coordinator
that called it starts or wakes backups itself, and ``backup init`` runs with
no server at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.backup_repository import check_backup_paths
from etsy_listings.core.application.position_coverage import widens
from etsy_listings.core.application.refusals import InvalidSettingsEditError
from etsy_listings.core.application.workspace_settings import (
    BACKUP,
    BACKUP_DESTINATIONS,
    CONCURRENCY,
    EDITABLE_KEYS,
    TEMPLATE_POSITIONS,
    SettingsView,
)
from etsy_listings.core.backup.destinations import create_destination
from etsy_listings.core.errors import RefusedError
from etsy_listings.core.render.positions import PositionLimits
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.workspace import Workspace


class Wakes(Protocol):
    """A coordinator that looks again when told something changed."""

    def wake(self) -> None: ...


class CoversPositions(Protocol):
    """Queues coverage inference for the positioned templates whose evidence
    misses ``limits``, which widened ``saved``. The host decides when the
    jobs are queued (the server, after it has answered)."""

    def cover_widened(self, saved: PositionLimits, limits: PositionLimits) -> None: ...


@dataclass(frozen=True)
class SettingsCoordinators:
    """The coordinators a save may need to tell; any left None is not told."""

    ai_queue: Wakes | None = None
    backups: Wakes | None = None
    coverage: CoversPositions | None = None


def save_settings(
    workspace: Workspace,
    *,
    expected_revision: str,
    changes: Mapping[str, object],
    editable: tuple[str, ...] = EDITABLE_KEYS,
    coordinators: SettingsCoordinators | None = None,
) -> SettingsView:
    """Apply ``changes`` as :func:`workspace_settings.edit_settings` does,
    then set off what they call for; the saved view. Refused with
    ``SettingsRevisionConflictError`` or ``InvalidSettingsEditError`` before
    anything is written, and then nothing is told."""
    told = coordinators or SettingsCoordinators()
    before = _saved_limits(workspace, changes) if told.coverage is not None else None
    added = _added_destinations(workspace, changes)
    view = workspace_settings.edit_settings(
        workspace, expected_revision=expected_revision, changes=changes, editable=editable
    )
    _create_folders(added)
    _tell(told, changes, before, view)
    return view


def check_settings_save(
    workspace: Workspace,
    *,
    expected_revision: str,
    changes: Mapping[str, object],
    editable: tuple[str, ...] = EDITABLE_KEYS,
) -> None:
    """What :func:`save_settings` would refuse for the same changes now,
    writing nothing: for an owner that saves only after a long step, such as
    backup provisioning's copy."""
    _added_destinations(workspace, changes)
    workspace_settings.check_settings_edit(
        workspace, expected_revision=expected_revision, changes=changes, editable=editable
    )


def _tell(
    told: SettingsCoordinators,
    changes: Mapping[str, object],
    before: PositionLimits | None,
    view: SettingsView,
) -> None:
    if told.ai_queue is not None and CONCURRENCY in changes:
        told.ai_queue.wake()
    if told.backups is not None and any(_is_backup(key) for key in changes):
        told.backups.wake()
    after = view.settings.template_positions
    if told.coverage is not None and before is not None and widens(after, before):
        told.coverage.cover_widened(before, after)


def _is_backup(key: str) -> bool:
    return key == BACKUP or key.startswith(f"{BACKUP}.")


def _saved_limits(workspace: Workspace, changes: Mapping[str, object]) -> PositionLimits | None:
    """The limits as saved before this edit, when it edits them; None when
    it does not, or the file does not load (the edit itself refuses that)."""
    if TEMPLATE_POSITIONS not in changes:
        return None
    saved = workspace.settings_if_readable(skipping="comparing saved position limits")
    return saved.template_positions if saved is not None else None


# ----------------------------------------------------------- destinations


def _added_destinations(workspace: Workspace, changes: Mapping[str, object]) -> tuple[Path, ...]:
    """The destinations this save adds, refused unless each can be created."""
    edited = _edited_destinations(changes)
    if edited is None:
        return ()
    backup = workspace_settings.read_settings(workspace).settings.backup
    known = set(backup.destinations) if backup is not None else set()
    offered = tuple(to_native_path(str(path)) for path in edited)
    storage = None if backup is None else backup.repository
    _refuse_overlapping(workspace, storage, offered)
    added = tuple(path for path in offered if path not in known)
    _refuse_unreachable(added)
    return added


def _edited_destinations(changes: Mapping[str, object]) -> Sequence[object] | None:
    """The destinations list this save writes: Setup's own key, or the one
    in a whole new ``backup:`` block."""
    edited = changes.get(BACKUP_DESTINATIONS)
    block = changes.get(BACKUP)
    if edited is None and isinstance(block, Mapping):
        edited = block.get("destinations")
    if not isinstance(edited, Sequence) or isinstance(edited, str):
        return None
    return edited


def _refuse_overlapping(
    workspace: Workspace, storage: Path | None, paths: tuple[Path, ...]
) -> None:
    if storage is not None and not storage.is_absolute():
        storage = None  # A repository path carried over from another operating system.
    try:
        check_backup_paths(workspace, storage, paths)
    except RefusedError as exc:
        raise InvalidSettingsEditError({BACKUP_DESTINATIONS: str(exc)}) from exc


def _refuse_unreachable(destinations: Sequence[Path]) -> None:
    """``create_destination``'s own refusal, made before anything is
    written, naming the field the form shows it under."""
    for path in destinations:
        _refuse_invalid_folder(path)
    missing = [path for path in destinations if not path.is_dir() and not path.parent.is_dir()]
    if missing:
        listed = "; ".join(
            f"{path.parent} does not exist, so {path} cannot be created" for path in missing
        )
        raise InvalidSettingsEditError(
            {
                BACKUP_DESTINATIONS: f"{listed}. Connect the drive or sync folder, or choose "
                "another folder."
            }
        )


def _refuse_invalid_folder(path: Path) -> None:
    if not path.is_absolute():
        raise InvalidSettingsEditError({BACKUP_DESTINATIONS: f"{path} is not a full folder path."})
    if path.exists() and not path.is_dir():
        raise InvalidSettingsEditError({BACKUP_DESTINATIONS: f"{path} is a file. Choose a folder."})


def _create_folders(destinations: Sequence[Path]) -> None:
    """Through the copy's own ``create_destination``, the one place a
    destination folder is made."""
    for path in destinations:
        create_destination(path)

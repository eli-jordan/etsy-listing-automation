"""A workspace with backups configured, for the backup operation tests.

Every backup test needs the same two files before it can assert anything: a
``backup:`` block in ``settings.yaml`` naming folders under ``tmp_path``, and
usually the password in the workspace ``.env``. :func:`configure_backups`
writes both, so a change to the block's shape is made here once, and the
call site shows only the folders and options the test cares about.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from etsy_listings.core.application.backup_repository import (
    configured_backup,
    create_repository,
)
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.backup.repository import OpenRepository
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

PASSWORD = "correct horse battery staple"
"""Long enough for the set-up form's minimum."""


def configure_backups(
    root: Path,
    storage: Path,
    *,
    destinations: Sequence[Path] = (),
    restic_binary: Path | None = None,
    interval_hours: int | None = None,
    password: str | None = PASSWORD,
    workspace_id: str | None = None,
    retention: RetentionSettings | None = None,
) -> Workspace:
    """Replace ``root``'s ``settings.yaml`` with a ``backup:`` block naming
    ``storage``, and its ``.env`` with ``password`` unless that is None; the
    workspace at ``root``. ``restic_binary`` names a restic so nothing is
    downloaded; tests that never run restic pass any path. Without a
    ``workspace_id`` the first run writes one, as for a block written by hand."""
    block: dict[str, Any] = {"repository": storage.as_posix()}
    if destinations:
        block["destinations"] = [path.as_posix() for path in destinations]
    if restic_binary is not None:
        block["restic_binary"] = restic_binary.as_posix()
    if interval_hours is not None:
        block["interval_hours"] = interval_hours
    if workspace_id is not None:
        block["workspace_id"] = workspace_id
    if retention is not None:
        block["retention"] = retention.model_dump()
    (root / "settings.yaml").write_text(
        yaml.safe_dump({"backup": block}, sort_keys=False), encoding="utf-8"
    )
    if password is not None:
        (root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={password}\n", encoding="utf-8")
    return Workspace.discover(root_override=root)


def initialise(workspace: Workspace, home: Path, *, restic: OpenRepository | None = None) -> str:
    """Create the configured repository as ``backup init`` does, storing
    :data:`PASSWORD` unless one is stored; its restic id."""
    backup = configured_backup(workspace, binaries=ResticBinaries(home=home), restic=restic)
    return create_repository(backup, backup.password or PASSWORD, store=backup.password is None)

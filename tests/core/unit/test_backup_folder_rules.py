"""Which folders a configured backup accepts (workspace-backup spec,
*Configuration*): the one place the separation of the workspace, the backup
storage folder and the destinations is tested. A restore target's refusals
are test_backup_restore.py's, through the restore that makes them.

Paths are written against ``{tmp}`` (this test's folder) and ``{ws}`` (the
workspace inside it); ``{WS}`` is the workspace path in upper case, which
Windows treats as the same folder.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import (
    ConfiguredBackup,
    configured_backup,
    has_repository,
)
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.config.settings import BackupSettings
from etsy_listings.core.errors import RefusedError
from etsy_listings.core.workspace.workspace import Workspace

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows folds the case of paths")
OVERLAPS = "overlaps"


def _path(template: str, tmp: Path, workspace: Path) -> Path:
    return Path(
        template.format(tmp=tmp.as_posix(), ws=workspace.as_posix(), WS=str(workspace).upper())
    )


def _backup(
    workspace_root: Path, storage: str, destinations: Sequence[str] = ("{tmp}/cloud",)
) -> ConfiguredBackup:
    tmp = workspace_root.parent
    settings = BackupSettings(
        repository=_path(storage, tmp, workspace_root),
        destinations=tuple(_path(path, tmp, workspace_root) for path in destinations),
    )
    workspace = Workspace.discover(root_override=workspace_root)
    return configured_backup(workspace, settings, binaries=ResticBinaries(home=tmp / "home"))


# --------------------------------------------------------------- separation


@pytest.mark.parametrize(
    ("storage", "destinations", "refused"),
    [
        pytest.param("{tmp}/backups", ["{tmp}/cloud"], None, id="separate folders"),
        pytest.param("{ws}/backups", [], OVERLAPS, id="storage inside the workspace"),
        pytest.param("{tmp}", [], OVERLAPS, id="workspace inside the storage folder"),
        pytest.param("{ws}", [], OVERLAPS, id="storage is the workspace"),
        pytest.param(
            "{tmp}/backups", ["{tmp}/backups/copy"], OVERLAPS, id="destination in storage"
        ),
        pytest.param("{tmp}/backups", ["{ws}/copy"], OVERLAPS, id="destination in the workspace"),
        pytest.param(
            "{tmp}/backups", ["{tmp}/c", "{tmp}/c/nas"], OVERLAPS, id="nested destinations"
        ),
        pytest.param("{tmp}/backups", ["{tmp}/c", "{tmp}/c"], OVERLAPS, id="the same destination"),
        pytest.param("backups", [], "not a full backup storage folder", id="relative storage"),
        pytest.param("{tmp}/backups", ["cloud"], None, id="relative destination left to the copy"),
        pytest.param(
            "{WS}/backups", [], OVERLAPS, id="storage in the workspace, other case", marks=WINDOWS
        ),
        pytest.param(
            "{tmp}/backups",
            ["{WS}"],
            OVERLAPS,
            id="destination is the workspace, other case",
            marks=WINDOWS,
        ),
    ],
)
def test_the_configuration_keeps_its_folders_apart(
    workspace_root: Path, storage: str, destinations: list[str], refused: str | None
) -> None:
    if refused is None:
        assert _backup(workspace_root, storage, destinations).storage.is_absolute()
        return
    with pytest.raises(RefusedError, match=refused):
        _backup(workspace_root, storage, destinations)


def _link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this machine does not let tests make symbolic links")


def test_a_storage_folder_reached_through_a_link_into_the_workspace_overlaps(
    workspace_root: Path, tmp_path: Path
) -> None:
    _link(tmp_path / "shortcut", workspace_root)

    with pytest.raises(RefusedError, match=OVERLAPS):
        _backup(workspace_root, "{tmp}/shortcut/backups")


# ------------------------------------------------------- repository present


@pytest.mark.parametrize(
    ("made", "present"),
    [
        pytest.param({"config": "file"}, True, id="restic's config file"),
        pytest.param({"config": "folder"}, False, id="a folder named config"),
        pytest.param({"data": "folder", "keys": "folder"}, False, id="a copy without its config"),
        pytest.param({}, False, id="an empty folder"),
    ],
)
def test_a_repository_is_present_only_with_its_config_file(
    tmp_path: Path, made: dict[str, str], *, present: bool
) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    for name, kind in made.items():
        if kind == "file":
            (folder / name).write_bytes(b"{}")
        else:
            (folder / name).mkdir()

    assert has_repository(folder) is present

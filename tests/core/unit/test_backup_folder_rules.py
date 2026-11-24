"""Which folders a configured backup accepts (workspace-backup spec,
*Configuration* and *Restore*): the one place the separation of the
workspace, the backup storage folder and the destinations is tested, and
the one place a restore target's refusals are.

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
from etsy_listings.core.application.backup_restore import LIVE_WORKSPACE
from etsy_listings.core.backup.binary import ResticBinaries
from etsy_listings.core.config.settings import BackupSettings
from etsy_listings.core.errors import RefusedError, UserFacingError
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


# ----------------------------------------------------------- restore target

STORAGE_FOLDER = "is in the backup storage folder"
DESTINATION = "is in a backup destination"
INSIDE = "is inside your live workspace"
HOLDS_FILES = "already holds files"


@pytest.mark.parametrize(
    ("target", "refused"),
    [
        pytest.param("{tmp}/restored", None, id="a new folder"),
        pytest.param("{tmp}/empty", None, id="an empty folder"),
        pytest.param("restored", "is not a full path", id="relative"),
        pytest.param("{ws}", LIVE_WORKSPACE, id="the live workspace"),
        pytest.param("{WS}", LIVE_WORKSPACE, id="the live workspace, other case", marks=WINDOWS),
        pytest.param("{ws}/old", INSIDE, id="inside the workspace"),
        pytest.param("{WS}/old", INSIDE, id="inside the workspace, other case", marks=WINDOWS),
        pytest.param("{tmp}/backups", STORAGE_FOLDER, id="the storage folder"),
        pytest.param("{tmp}/backups/old", STORAGE_FOLDER, id="inside the storage folder"),
        pytest.param("{tmp}/cloud", DESTINATION, id="an empty destination"),
        pytest.param("{tmp}/cloud/old", DESTINATION, id="inside a destination"),
        pytest.param("{tmp}/full", HOLDS_FILES, id="a folder with files"),
        pytest.param("{tmp}/notes.txt", HOLDS_FILES, id="a file"),
        pytest.param("{tmp}", HOLDS_FILES, id="the folder holding the workspace"),
    ],
)
def test_a_restore_target_must_be_new_and_outside_every_backup_folder(
    workspace_root: Path, tmp_path: Path, target: str, refused: str | None
) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "notes.txt").write_text("keep me")
    (tmp_path / "notes.txt").write_text("keep me")
    (tmp_path / "cloud").mkdir()
    backup = _backup(workspace_root, "{tmp}/backups")
    folder = _path(target, tmp_path, workspace_root)

    if refused is None:
        assert backup.check_restore_target(folder) == folder.resolve()
        return
    with pytest.raises(UserFacingError, match=refused):
        backup.check_restore_target(folder)


def test_a_restore_target_reached_through_a_link_into_the_workspace_is_inside_it(
    workspace_root: Path, tmp_path: Path
) -> None:
    _link(tmp_path / "shortcut", workspace_root)

    with pytest.raises(UserFacingError, match=INSIDE):
        _backup(workspace_root, "{tmp}/backups").check_restore_target(tmp_path / "shortcut" / "old")


def test_the_settings_as_they_read_now_protect_their_folders_too(
    workspace_root: Path, tmp_path: Path
) -> None:
    """The re-check just before restic writes: a destination saved since
    the operation began is refused as one."""
    backup = _backup(workspace_root, "{tmp}/backups")
    now = BackupSettings(repository=tmp_path / "moved", destinations=(tmp_path / "added",))

    for folder in (tmp_path / "added" / "old", tmp_path / "moved"):
        with pytest.raises(UserFacingError, match=DESTINATION):
            backup.check_restore_target(folder, now=now)


@WINDOWS
def test_a_letter_windows_keeps_apart_but_str_lower_folds_is_one_folder(
    workspace_root: Path, tmp_path: Path
) -> None:
    """Where the two "inside" rules this replaced disagreed. The Kelvin sign
    lower-cases to ``k`` in Python but not in ``os.path.normcase``, so the
    restore's old rule let this target through; the one rule refuses it, the
    safe side for a folder that only differs by such a letter."""
    backup = _backup(workspace_root, "{tmp}/k-store")

    with pytest.raises(UserFacingError, match=STORAGE_FOLDER):
        backup.check_restore_target(tmp_path / "K-store" / "old")


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

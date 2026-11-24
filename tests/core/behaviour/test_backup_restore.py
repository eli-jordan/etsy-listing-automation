"""A restore, prepared and run (workspace-backup spec, *Restore*; plan,
PR 7), against the in-memory repository: the one place a restore target's
refusals are tested, both before the repository opens and just before restic
writes. The coordinator's job around it is test_backup_restore_job.py's.

Paths are written against ``{tmp}`` (this test's folder) and ``{ws}`` (the
workspace inside it); ``{WS}`` is the workspace path in upper case, which
Windows treats as the same folder.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import LIVE_WORKSPACE
from etsy_listings.core.application.backup_restore import PreparedRestore, prepare_restore
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.repository import ResticCancelledError, RestoreProgress
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.errors import MissingError, UserFacingError
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.backups import configure_backups
from tests.support.restic import InMemoryRestic, snapshot_id

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows folds the case of paths")
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
SNAPSHOT = snapshot_id(1)

STORAGE_FOLDER = "is in the backup storage folder"
DESTINATION = "is in a backup destination"
INSIDE = "is inside your live workspace"
HOLDS_FILES = "already holds files"


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)


def _configure(workspace_root: Path, storage: str = "backups", *extra: Path) -> Workspace:
    tmp = workspace_root.parent
    return configure_backups(
        workspace_root,
        tmp / storage,
        destinations=[tmp / "cloud", *extra],
        restic_binary=tmp / "restic",
    )


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return _configure(workspace_root)


@pytest.fixture
def restic() -> InMemoryRestic:
    fake = InMemoryRestic(lambda: NOW)
    fake.snapshots += [NOW - timedelta(days=1), NOW - timedelta(hours=2)]
    return fake


def _prepare(
    workspace: Workspace, restic: InMemoryRestic, target: Path, snapshot: str = SNAPSHOT
) -> PreparedRestore:
    home = workspace.root.parent / "home"
    return prepare_restore(
        workspace, snapshot, target, binaries=ResticBinaries(home=home), restic=restic
    )


def _path(template: str, tmp: Path, workspace: Path) -> Path:
    return Path(
        template.format(tmp=tmp.as_posix(), ws=workspace.as_posix(), WS=str(workspace).upper())
    )


def _link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this machine does not let tests make symbolic links")


# ------------------------------------------------------------- the snapshot


def test_a_prepared_restore_writes_the_snapshot_and_reports_its_figures(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    heard: list[RestoreProgress] = []
    prepared = _prepare(workspace, restic, tmp_path / "restored")

    last = prepared.run(progress=heard.append)

    assert (prepared.snapshot.id, prepared.target) == (SNAPSHOT, (tmp_path / "restored").resolve())
    assert [figures.files_done for figures in heard] == [100, 400]
    assert last.files_done == 400
    assert restic.reads_without_lock == 1, "a backup underway does not hold the listing up"


def test_latest_is_the_newest_snapshot(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    assert _prepare(workspace, restic, tmp_path / "restored", "latest").snapshot.id == (
        snapshot_id(2)
    )


@pytest.mark.parametrize(
    ("ref", "missing"),
    [("deadbeef", "No backup has the id deadbeef."), ("0000", "0000 is ambiguous.")],
)
def test_a_snapshot_no_id_or_several_start_with_is_missing(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path, ref: str, missing: str
) -> None:
    with pytest.raises(MissingError, match=missing):
        _prepare(workspace, restic, tmp_path / "restored", ref)
    assert restic.ran("restore") == 0


def test_a_restore_stopped_before_it_starts_writes_nothing(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    stop = threading.Event()
    stop.set()

    with pytest.raises(ResticCancelledError):
        _prepare(workspace, restic, tmp_path / "restored").run(cancel=stop)
    assert restic.ran("restore") == 0


# ---------------------------------------------------- the target, prepared


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
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path, target: str, refused: str | None
) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "notes.txt").write_text("keep me")
    (tmp_path / "notes.txt").write_text("keep me")
    (tmp_path / "cloud").mkdir()
    folder = _path(target, tmp_path, workspace.root)

    if refused is None:
        _prepare(workspace, restic, folder).run()
        assert restic.ran("restore") == 1
        return
    with pytest.raises(UserFacingError, match=refused):
        _prepare(workspace, restic, folder)
    assert restic.operations == [], "refused before the repository opens"


def test_a_restore_target_reached_through_a_link_into_the_workspace_is_inside_it(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    _link(tmp_path / "shortcut", workspace.root)

    with pytest.raises(UserFacingError, match=INSIDE):
        _prepare(workspace, restic, tmp_path / "shortcut" / "old")


@WINDOWS
def test_a_letter_windows_keeps_apart_but_str_lower_folds_is_one_folder(
    workspace_root: Path, restic: InMemoryRestic, tmp_path: Path
) -> None:
    """Where the two "inside" rules backup_repository's replaced disagreed.
    The Kelvin sign lower-cases to ``k`` in Python but not in
    ``os.path.normcase``, so the restore's old rule let this target through;
    the one rule refuses it, the safe side for a folder that only differs by
    such a letter."""
    workspace = _configure(workspace_root, "k-store")

    with pytest.raises(UserFacingError, match=STORAGE_FOLDER):
        _prepare(workspace, restic, tmp_path / "K-store" / "old")


# ------------------------------------------- the target, just before restic


def test_files_that_land_in_the_target_after_preparing_stop_the_restore(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    target = tmp_path / "restored"
    target.mkdir()
    prepared = _prepare(workspace, restic, target)
    (target / "notes.txt").write_text("preserve me")

    with pytest.raises(UserFacingError, match=HOLDS_FILES):
        prepared.run()
    assert restic.ran("restore") == 0
    assert (target / "notes.txt").read_text() == "preserve me"


@pytest.mark.parametrize(
    ("saved", "target"),
    [
        pytest.param(("backups", "added"), "added", id="a destination added"),
        pytest.param(("added",), "added/old", id="the storage folder moved"),
    ],
)
def test_a_target_the_settings_made_a_backup_folder_since_preparing_is_refused(
    workspace: Workspace,
    restic: InMemoryRestic,
    tmp_path: Path,
    saved: tuple[str, ...],
    target: str,
) -> None:
    """A Setup save between preparing and running: the re-check reads
    ``settings.yaml`` afresh and refuses its folders as destinations."""
    prepared = _prepare(workspace, restic, tmp_path / target)
    storage, *added = saved
    _configure(workspace.root, storage, *(tmp_path / name for name in added))

    with pytest.raises(UserFacingError, match=DESTINATION):
        prepared.run()
    assert restic.ran("restore") == 0

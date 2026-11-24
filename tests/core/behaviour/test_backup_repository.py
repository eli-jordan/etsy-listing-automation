"""Creating, opening and reporting on a workspace's backup repository
through its configured backup (workspace-backup plan, PR 2): the ``backup:``
block, the ``.env`` password and the restic binary together, against the
in-memory repository. Which folders the configuration refuses is
test_backup_folder_rules.py's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import (
    BackupOffError,
    PasswordTooShortError,
    RepositoryNotEmptyError,
    ResticNotInstalledError,
    backup_status,
    configured_backup,
    create_repository,
)
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.repository import ResticError, WrongPasswordError
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR, MissingCredentialError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.backups import PASSWORD, configure_backups
from tests.support.restic import InMemoryRestic, snapshot_id

NOW = datetime(2026, 11, 23, 8, tzinfo=UTC)


def _restic() -> InMemoryRestic:
    return InMemoryRestic(lambda: NOW)


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def repository(tmp_path: Path, workspace: Workspace) -> Path:
    """A ``backup:`` block naming a repository under ``tmp_path``, run with a
    restic named in the setting, so nothing is downloaded."""
    path = tmp_path / "backups"
    configure_backups(workspace.root, path, restic_binary=tmp_path / "restic", password=None)
    return path


@pytest.fixture
def binaries(tmp_path: Path) -> ResticBinaries:
    return ResticBinaries(home=tmp_path / "home")


def _env(workspace: Workspace) -> str:
    return (workspace.root / layout.ENV_FILE).read_text(encoding="utf-8")


def _create(
    workspace: Workspace,
    binaries: ResticBinaries,
    restic: InMemoryRestic,
    password: str = PASSWORD,
    *,
    store: bool = True,
) -> str:
    backup = configured_backup(workspace, binaries=binaries, restic=restic)
    return create_repository(backup, password, store=store)


def test_without_a_backup_block_there_is_nothing_to_create(
    workspace: Workspace, binaries: ResticBinaries
) -> None:
    with pytest.raises(BackupOffError, match="backup:"):
        configured_backup(workspace, binaries=binaries, restic=_restic())


def test_creating_stores_the_password_then_initialises(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    restic = _restic()
    restic.password = PASSWORD

    created = _create(workspace, binaries, restic)

    assert created == "f00d"
    assert f"{BACKUP_PASSWORD_VAR}={PASSWORD}" in _env(workspace)
    assert restic.operations == ["init"]
    assert (repository / "config").is_file()


def test_a_failed_init_keeps_the_stored_password(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    """Stored before restic runs, so no repository can exist whose password
    this machine never recorded."""
    restic = _restic()
    restic.fail("init", ResticError("restic: Fatal: disk full", exit_code=1))

    with pytest.raises(ResticError, match="disk full"):
        _create(workspace, binaries, restic)

    assert f"{BACKUP_PASSWORD_VAR}={PASSWORD}" in _env(workspace)


def test_a_password_already_stored_is_not_written_again(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    (workspace.root / layout.ENV_FILE).write_text(
        f"# mine\n{BACKUP_PASSWORD_VAR}={PASSWORD}\n", encoding="utf-8"
    )

    _create(workspace, binaries, _restic(), store=False)

    assert _env(workspace) == f"# mine\n{BACKUP_PASSWORD_VAR}={PASSWORD}\n"


def test_a_short_password_is_refused_before_anything_is_written(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    with pytest.raises(PasswordTooShortError, match="12"):
        _create(workspace, binaries, _restic(), "eleven-char")

    assert not (workspace.root / layout.ENV_FILE).exists()


def test_a_folder_holding_files_is_refused(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    repository.mkdir()
    (repository / "holiday.jpg").write_bytes(b"\xff\xd8")

    with pytest.raises(RepositoryNotEmptyError, match=str(repository).replace("\\", "\\\\")):
        _create(workspace, binaries, _restic())

    assert not (workspace.root / layout.ENV_FILE).exists()


def test_an_empty_existing_folder_is_used(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    repository.mkdir()

    created = _create(workspace, binaries, _restic())

    assert created == "f00d"


def test_opening_needs_the_stored_password(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    with pytest.raises(MissingCredentialError) as caught:
        configured_backup(workspace, binaries=binaries).open()

    assert caught.value.variable == BACKUP_PASSWORD_VAR


def test_opening_never_downloads_restic(
    workspace: Workspace, tmp_path: Path, binaries: ResticBinaries
) -> None:
    configure_backups(workspace.root, tmp_path / "b")

    with pytest.raises(ResticNotInstalledError, match="backup init"):
        configured_backup(workspace, binaries=binaries).open()

    assert not (tmp_path / "home").exists()


def test_status_of_a_workspace_without_backups_says_they_are_off(
    workspace: Workspace, binaries: ResticBinaries
) -> None:
    status = backup_status(workspace, binaries=binaries, restic=_restic())

    assert status.settings is None
    assert status.problem is None


def test_status_lists_the_snapshots_read_without_a_lock(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    configure_backups(workspace.root, repository, restic_binary=repository.parent / "restic")
    restic = _restic()
    restic.snapshots.append(NOW)

    status = backup_status(workspace, binaries=binaries, restic=restic)

    assert status.problem is None
    assert status.settings is not None
    assert status.settings.repository == repository
    assert status.binary == repository.parent / "restic"
    assert [s.id for s in status.snapshots or ()] == [snapshot_id(1)]
    assert (restic.operations, restic.reads_without_lock) == (["snapshots"], 1)


def test_status_reports_what_stops_the_repository_opening(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    configure_backups(
        workspace.root,
        repository,
        restic_binary=repository.parent / "restic",
        password="not-the-one-at-all",
    )
    restic = _restic()
    restic.password = PASSWORD

    status = backup_status(workspace, binaries=binaries, restic=restic)

    assert status.snapshots is None
    assert status.problem is not None
    assert "wrong password" in status.problem
    assert isinstance(status.error, WrongPasswordError)
    assert "not-the-one-at-all" not in status.problem


def test_status_reports_a_missing_password_without_running_restic(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    status = backup_status(workspace, binaries=binaries, restic=_restic())

    assert status.problem is not None
    assert BACKUP_PASSWORD_VAR in status.problem

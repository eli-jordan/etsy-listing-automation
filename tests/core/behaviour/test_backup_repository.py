"""Creating, opening and checking a workspace's backup repository
(workspace-backup plan, PR 2): the ``backup:`` block, the ``.env`` password
and the restic binary together, with restic replaced by recorded replies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application.backup_repository import (
    BackupOffError,
    PasswordTooShortError,
    RepositoryNotEmptyError,
    ResticNotInstalledError,
    backup_status,
    create_repository,
    open_repository,
)
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.restic import WrongPasswordError
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR, MissingCredentialError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.restic import Reply, ScriptedRestic, exit_error

PASSWORD = "correct horse battery staple"
INITIALIZED = {"message_type": "initialized", "id": "62d06b01", "repository": "r"}


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
    workspace.settings_file().write_text(
        f"backup:\n  repository: {path.as_posix()}\n"
        f"  restic_binary: {(tmp_path / 'restic').as_posix()}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def binaries(tmp_path: Path) -> ResticBinaries:
    return ResticBinaries(home=tmp_path / "home")


def _env(workspace: Workspace) -> str:
    return (workspace.root / layout.ENV_FILE).read_text(encoding="utf-8")


def test_without_a_backup_block_there_is_nothing_to_create(
    workspace: Workspace, binaries: ResticBinaries
) -> None:
    with pytest.raises(BackupOffError, match="backup:"):
        create_repository(workspace, PASSWORD, binaries=binaries, launch=ScriptedRestic())


def test_creating_stores_the_password_then_initialises(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    launcher = ScriptedRestic(Reply(stdout=[INITIALIZED]))

    created = create_repository(workspace, PASSWORD, binaries=binaries, launch=launcher)

    assert created == "62d06b01"
    assert f"{BACKUP_PASSWORD_VAR}={PASSWORD}" in _env(workspace)
    assert launcher.commands == [["init"]]
    assert launcher.launches[0].argv[2] == str(repository)
    assert launcher.launches[0].env["RESTIC_PASSWORD"] == PASSWORD


def test_a_failed_init_keeps_the_stored_password(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    """Stored before restic runs, so no repository can exist whose password
    this machine never recorded."""
    launcher = ScriptedRestic(Reply(stderr=exit_error(1, "Fatal: disk full"), exit_code=1))

    with pytest.raises(Exception, match="disk full"):
        create_repository(workspace, PASSWORD, binaries=binaries, launch=launcher)

    assert f"{BACKUP_PASSWORD_VAR}={PASSWORD}" in _env(workspace)


def test_a_password_already_stored_is_not_written_again(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    (workspace.root / layout.ENV_FILE).write_text(
        f"# mine\n{BACKUP_PASSWORD_VAR}={PASSWORD}\n", encoding="utf-8"
    )

    create_repository(
        workspace,
        PASSWORD,
        binaries=binaries,
        launch=ScriptedRestic(Reply(stdout=[INITIALIZED])),
        store=False,
    )

    assert _env(workspace) == f"# mine\n{BACKUP_PASSWORD_VAR}={PASSWORD}\n"


def test_a_short_password_is_refused_before_anything_is_written(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    with pytest.raises(PasswordTooShortError, match="12"):
        create_repository(workspace, "eleven-char", binaries=binaries, launch=ScriptedRestic())

    assert not (workspace.root / layout.ENV_FILE).exists()


def test_a_folder_holding_files_is_refused(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    repository.mkdir()
    (repository / "holiday.jpg").write_bytes(b"\xff\xd8")

    with pytest.raises(RepositoryNotEmptyError, match=str(repository).replace("\\", "\\\\")):
        create_repository(workspace, PASSWORD, binaries=binaries, launch=ScriptedRestic())

    assert not (workspace.root / layout.ENV_FILE).exists()


def test_an_empty_existing_folder_is_used(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    repository.mkdir()

    created = create_repository(
        workspace, PASSWORD, binaries=binaries, launch=ScriptedRestic(Reply(stdout=[INITIALIZED]))
    )

    assert created == "62d06b01"


def test_opening_needs_the_stored_password(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    with pytest.raises(MissingCredentialError) as caught:
        open_repository(workspace, binaries=binaries)

    assert caught.value.variable == BACKUP_PASSWORD_VAR


def test_opening_never_downloads_restic(
    workspace: Workspace, tmp_path: Path, binaries: ResticBinaries
) -> None:
    workspace.settings_file().write_text(
        f"backup:\n  repository: {(tmp_path / 'b').as_posix()}\n", encoding="utf-8"
    )
    (workspace.root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")

    with pytest.raises(ResticNotInstalledError, match="backup init"):
        open_repository(workspace, binaries=binaries)

    assert not (tmp_path / "home").exists()


def test_status_of_a_workspace_without_backups_says_they_are_off(
    workspace: Workspace, binaries: ResticBinaries
) -> None:
    status = backup_status(workspace, binaries=binaries, launch=ScriptedRestic())

    assert status.settings is None
    assert status.problem is None


def test_status_lists_the_snapshots_read_without_a_lock(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    (workspace.root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
    snapshot = {
        "time": "2026-11-23T08:00:00Z",
        "paths": ["/w"],
        "hostname": "h",
        "id": "a" * 64,
        "short_id": "aaaaaaaa",
    }
    launcher = ScriptedRestic(Reply(stdout=[[snapshot]]))

    status = backup_status(workspace, binaries=binaries, launch=launcher)

    assert status.problem is None
    assert status.settings is not None
    assert status.settings.repository == repository
    assert status.binary == repository.parent / "restic"
    assert [s.short_id for s in status.snapshots or ()] == ["aaaaaaaa"]
    assert launcher.commands == [["--no-lock", "snapshots"]]


def test_status_reports_what_stops_the_repository_opening(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    (workspace.root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}=not-the-one-at-all\n")
    launcher = ScriptedRestic(
        Reply(stderr=exit_error(12, "Fatal: wrong password or no key found"), exit_code=12)
    )

    status = backup_status(workspace, binaries=binaries, launch=launcher)

    assert status.snapshots is None
    assert status.problem is not None
    assert "wrong password" in status.problem
    assert isinstance(status.error, WrongPasswordError)
    assert "not-the-one-at-all" not in status.problem


def test_status_reports_a_missing_password_without_running_restic(
    workspace: Workspace, repository: Path, binaries: ResticBinaries
) -> None:
    status = backup_status(workspace, binaries=binaries, launch=ScriptedRestic())

    assert status.problem is not None
    assert BACKUP_PASSWORD_VAR in status.problem

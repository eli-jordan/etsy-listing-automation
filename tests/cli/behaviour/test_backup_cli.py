"""``etsy-listings backup init|snapshots|status`` (workspace-backup spec,
*CLI*; plan, PR 2).

Refusals run without restic. The journeys that create and read a repository
are marked ``restic`` and run the pinned binary against folders in
``tmp_path`` (plan, P3). ``Path.home`` points under ``tmp_path`` throughout,
so nothing reaches the real ``~/.etsy-listings`` (P2).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from etsy_listings.cli.app import app
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.backup.state import HISTORY_FILE, STATE_FILE
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR, Secrets
from etsy_listings.core.workspace import layout

from tests.support import scripted as scripted_prompts
from tests.support.backups import PASSWORD, configure_backups

runner = CliRunner()
Script = Callable[[scripted_prompts.Answers], scripted_prompts.Scripted]


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.delenv(layout.ROOT_ENV_VAR, raising=False)
    return home


@pytest.fixture
def repository(tmp_path: Path, workspace_root: Path) -> Path:
    path = tmp_path / "backups"
    configure_backups(workspace_root, path, destinations=[tmp_path / "cloud"], password=None)
    return path


def _store_password(workspace_root: Path, repository: Path, password: str = PASSWORD) -> None:
    configure_backups(
        workspace_root, repository, destinations=[repository.with_name("cloud")], password=password
    )


def _run(workspace_root: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["backup", *args, "--root", str(workspace_root)])
    return result.exit_code, result.output


def _env(workspace_root: Path) -> str:
    return (workspace_root / layout.ENV_FILE).read_text(encoding="utf-8")


# ------------------------------------------------------------- without restic


def test_without_a_backup_block_init_explains_and_writes_nothing(workspace_root: Path) -> None:
    code, output = _run(workspace_root, "init")

    assert code == 1
    assert "Backups are off" in output
    assert not (workspace_root / layout.ENV_FILE).exists()


def test_status_says_backups_are_off(workspace_root: Path) -> None:
    code, output = _run(workspace_root, "status")

    assert code == 0
    assert "Backups are off" in output


def test_a_short_password_is_refused_and_nothing_is_written(
    workspace_root: Path, repository: Path, scripted: Script
) -> None:
    scripted({"backup password": "too-short"})

    code, output = _run(workspace_root, "init")

    assert code == 1
    assert "at least 12 characters" in output
    assert not (workspace_root / layout.ENV_FILE).exists()
    assert not repository.exists()


def test_a_password_typed_differently_twice_is_refused(
    workspace_root: Path, repository: Path, scripted: Script
) -> None:
    scripted({"new backup password": PASSWORD, "again": PASSWORD + "!"})

    code, output = _run(workspace_root, "init")

    assert code == 1
    assert "did not match" in output
    assert not (workspace_root / layout.ENV_FILE).exists()


def test_status_without_restic_installed_says_how_to_get_it(
    workspace_root: Path, repository: Path, monkeypatch: pytest.MonkeyPatch, isolated: Path
) -> None:
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)
    _store_password(workspace_root, repository)

    code, output = _run(workspace_root, "status")

    assert code == 1
    assert str(repository) in output
    assert "backup init" in output
    assert not isolated.exists()


def test_snapshots_refuses_a_storage_folder_inside_the_workspace(
    workspace_root: Path, tmp_path: Path, isolated: Path
) -> None:
    """Resolved as every other command is, so restic never starts."""
    configure_backups(workspace_root, workspace_root / "backups", restic_binary=tmp_path / "r")

    code, output = _run(workspace_root, "snapshots")

    assert code == 1
    assert "overlaps" in output
    assert not isolated.exists()


def test_run_without_a_password_fails_and_is_recorded(
    workspace_root: Path, repository: Path, isolated: Path
) -> None:
    code, output = _run(workspace_root, "run")

    assert code == 1
    assert BACKUP_PASSWORD_VAR in output
    assert '"outcome": "failed"' in (isolated / ".etsy-listings" / HISTORY_FILE).read_text()


# ---------------------------------------------------------------- with restic


@pytest.fixture
def with_restic(restic_binary: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    return restic_binary


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_init_asks_for_a_password_stores_it_and_creates_the_repository(
    workspace_root: Path, repository: Path, scripted: Script
) -> None:
    script = scripted({"new backup password": PASSWORD, "again": PASSWORD})

    code, output = _run(workspace_root, "init")

    assert code == 0, output
    assert (repository / "config").is_file()
    assert Secrets.load(workspace_root / layout.ENV_FILE).require_backup_password() == PASSWORD
    assert "password manager" in output
    assert PASSWORD not in output
    assert len(script.asked) == 2


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_init_uses_a_stored_password_without_asking(
    workspace_root: Path, repository: Path, scripted: Script
) -> None:
    _store_password(workspace_root, repository)
    script = scripted({})

    code, output = _run(workspace_root, "init")

    assert code == 0, output
    assert script.asked == []
    assert (repository / "config").is_file()


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_snapshots_and_status_read_the_new_repository(
    workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    _store_password(workspace_root, repository)
    assert _run(workspace_root, "init")[0] == 0

    code, output = _run(workspace_root, "snapshots")
    assert (code, output.strip()) == (0, "No snapshots yet.")

    code, output = _run(workspace_root, "snapshots", "--json")
    assert (code, json.loads(output)) == (0, [])

    code, output = _run(workspace_root, "status")
    assert code == 0, output
    assert str(repository) in output
    assert str(tmp_path / "cloud") in output
    assert "every 12 hours" in output
    assert "0 snapshots" in output
    assert PASSWORD not in output


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_status_reports_a_wrong_password(workspace_root: Path, repository: Path) -> None:
    _store_password(workspace_root, repository)
    assert _run(workspace_root, "init")[0] == 0
    _store_password(workspace_root, repository, "another password")

    code, output = _run(workspace_root, "status")

    assert code == 1
    assert "wrong password" in output
    assert "another password" not in output


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_status_json_reports_the_configuration(workspace_root: Path, repository: Path) -> None:
    _store_password(workspace_root, repository)
    assert _run(workspace_root, "init")[0] == 0

    code, output = _run(workspace_root, "status", "--json")

    report = json.loads(output)
    assert code == 0
    assert report["enabled"] is True
    assert report["repository"] == str(repository)
    assert report["interval_hours"] == 12
    assert report["snapshots"] == 0
    assert report["problem"] is None


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_run_backs_up_copies_then_check_finds_no_errors(
    workspace_root: Path, repository: Path
) -> None:
    _store_password(workspace_root, repository)
    assert _run(workspace_root, "init")[0] == 0
    cloud = repository.with_name("cloud")
    cloud.mkdir()

    code, output = _run(workspace_root, "run")
    assert code == 0, output
    assert "Pruning" in output
    assert f"Copied to {cloud}." in output
    assert (cloud / "config").read_bytes() == (repository / "config").read_bytes()
    snapshot = json.loads(_run(workspace_root, "snapshots", "--json")[1])
    assert len(snapshot) == 1
    assert f"snapshot {snapshot[0]['short_id']}" in output

    code, output = _run(workspace_root, "check")
    assert (code, output.strip()) == (0, "The backup repository has no errors.")


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_check_of_a_damaged_repository_fails_and_is_recorded(
    workspace_root: Path, repository: Path, isolated: Path
) -> None:
    _store_password(workspace_root, repository)
    assert _run(workspace_root, "init")[0] == 0
    assert _run(workspace_root, "run")[0] == 0
    for pack in (repository / "data").rglob("*"):
        if pack.is_file():
            pack.unlink()

    code, output = _run(workspace_root, "check")

    assert code == 1
    assert "has no errors" not in output
    assert "restic:" in output
    state = json.loads((isolated / ".etsy-listings" / STATE_FILE).read_text())
    assert state["last_check"]["ok"] is False


def test_a_refused_restore_prints_why_and_exits_1(workspace_root: Path, repository: Path) -> None:
    """Which targets are refused is test_backup_restore.py's."""
    assert _run(workspace_root, "restore", "latest", str(workspace_root)) == (
        1,
        "That's your live workspace. Choose a new, empty folder.\n",
    )


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_restore_writes_a_snapshot_into_a_new_folder(
    workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    _store_password(workspace_root, repository)
    assert _run(workspace_root, "init")[0] == 0
    assert _run(workspace_root, "run")[0] == 0
    target = tmp_path / "restored"

    code, output = _run(workspace_root, "restore", "latest", target.as_posix())

    assert code == 0, output
    assert f"into {target}" in output
    assert (target / "settings.yaml").read_bytes() == (
        workspace_root / "settings.yaml"
    ).read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="translation is a Windows-only concern")
def test_restore_reads_a_cygwin_style_target_as_the_windows_folder(
    workspace_root: Path, repository: Path
) -> None:
    """``/cygdrive/c/...`` from a Cygwin shell names the same folder as
    ``C:/...``, so the live workspace is still refused."""
    drive, rest = workspace_root.drive, workspace_root.as_posix()[len(workspace_root.drive) :]
    cygwin = f"/cygdrive/{drive.rstrip(':').lower()}{rest}"

    assert _run(workspace_root, "restore", "latest", cygwin) == (
        1,
        "That's your live workspace. Choose a new, empty folder.\n",
    )


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_init_connects_the_backup_a_destination_already_holds(
    workspace_root: Path, repository: Path, scripted: Script
) -> None:
    """A new machine: the storage folder is gone, the destination copy and
    settings.yaml are there, and .env is not."""
    _store_password(workspace_root, repository)
    cloud = repository.with_name("cloud")
    cloud.mkdir()
    assert _run(workspace_root, "init")[0] == 0
    assert _run(workspace_root, "run")[0] == 0
    shutil.rmtree(repository)
    (workspace_root / layout.ENV_FILE).unlink()

    scripted({"password of the existing backup": "not the password at all"})
    wrong, refused = _run(workspace_root, "init")
    left_behind = sorted(path.name for path in repository.parent.iterdir())
    script = scripted({"password of the existing backup": PASSWORD})
    code, output = _run(workspace_root, "init")

    assert wrong == 1, refused
    assert "does not open" in refused
    assert "backups" not in left_behind
    assert not any(".connecting-" in name for name in left_behind)
    assert code == 0, output
    assert f"Copying the backup in {cloud} to {repository}..." in output
    assert f"Connected to the backup in {cloud}: 1 snapshots, copied to {repository}." in output
    assert "password manager" in output
    assert len(script.asked) == 1
    assert Secrets.load(workspace_root / layout.ENV_FILE).require_backup_password() == PASSWORD
    assert (repository / "config").read_bytes() == (cloud / "config").read_bytes()

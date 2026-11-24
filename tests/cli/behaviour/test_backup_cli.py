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

runner = CliRunner()
PASSWORD = "correct horse battery staple"
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
    cloud = (tmp_path / "cloud").as_posix()
    (workspace_root / "settings.yaml").write_text(
        f"backup:\n  repository: {path.as_posix()}\n  destinations: [{cloud}]\n",
        encoding="utf-8",
    )
    return path


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
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")

    code, output = _run(workspace_root, "status")

    assert code == 1
    assert str(repository) in output
    assert "backup init" in output
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
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
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
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
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
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
    assert _run(workspace_root, "init")[0] == 0
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}=another password\n")

    code, output = _run(workspace_root, "status")

    assert code == 1
    assert "wrong password" in output
    assert "another password" not in output


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_status_json_reports_the_configuration(workspace_root: Path, repository: Path) -> None:
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
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
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
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
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
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


def test_restore_refuses_the_live_workspace_and_a_folder_with_files(
    workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    full = tmp_path / "full"
    full.mkdir()
    (full / "notes.txt").write_text("keep me")

    live = _run(workspace_root, "restore", "latest", str(workspace_root))
    used = _run(workspace_root, "restore", "latest", str(full))

    assert live == (1, "That's your live workspace. Choose a new, empty folder.\n")
    assert used[0] == 1
    assert "already holds files" in used[1]


@pytest.mark.restic
@pytest.mark.usefixtures("with_restic")
def test_restore_writes_a_snapshot_into_a_new_folder(
    workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")
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

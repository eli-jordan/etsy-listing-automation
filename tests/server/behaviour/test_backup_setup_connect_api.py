"""First-time set-up when a destination already holds a backup: it connects
that copy instead of creating a repository (workspace-backup spec, *Set-up*),
through ``POST /api/backup/setup`` with the app's lifespan running. restic is
the by-command fake unless a test is marked ``restic``; every folder is under
``tmp_path`` (plan, P2).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from etsy_listings.core.application.backup_coordinator import (
    BackupCoordinator,
    BackupEnvironment,
)
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.repository import ResticError
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import wait_for
from tests.support.backups import PASSWORD, configure_backups, initialise
from tests.support.repository_files import FakeRepository, files, identities
from tests.support.restic import InMemoryRestic

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(tmp_path / "restic"))


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def restic() -> InMemoryRestic:
    fake = InMemoryRestic(lambda: NOW)
    fake.password = PASSWORD
    fake.snapshots.append(NOW - timedelta(days=1))
    return fake


@pytest.fixture
def app(workspace_root: Path, tmp_path: Path, restic: InMemoryRestic) -> FastAPI:
    environment = BackupEnvironment(home=tmp_path / "home", restic=restic, now=lambda: NOW)
    workspace = Workspace.discover(root_override=workspace_root)
    return create_app(workspace, backup=environment)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _ok(response: Any, status: int = 202) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def _set_up(
    client: TestClient, storage: Path, destinations: list[Path], password: str = PASSWORD
) -> Any:
    revision = client.get("/api/admin/settings").json()["revision"]
    body = {
        "revision": revision,
        "repository": str(storage),
        "destinations": [str(path) for path in destinations],
        "interval_hours": 12,
        "retention": {"keep_within_days": 7, "weekly": 4, "monthly": 3},
        "password": password,
    }
    return client.post("/api/backup/setup", json=body)


def _history(client: TestClient) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = client.get("/api/backup/history").json()["runs"]
    return runs


def _copy(folder: Path, *labels: str, repository_id: str = "fake") -> FakeRepository:
    """A destination copy with one backup per label."""
    copy = FakeRepository(folder, repository_id=repository_id)
    for label in labels:
        copy.backup(label)
    return copy


def _untouched(workspace_root: Path, storage: Path) -> dict[str, object]:
    """Everything a refused set-up must leave as it was."""
    env = workspace_root / layout.ENV_FILE
    return {
        "settings": (workspace_root / "settings.yaml").exists(),
        "env": env.read_bytes() if env.exists() else None,
        "beside": sorted(path.name for path in storage.parent.iterdir()),
    }


def _without_locks(tree: dict[str, bytes]) -> dict[str, bytes]:
    return {name: data for name, data in tree.items() if not name.startswith("locks")}


def test_set_up_connects_the_backup_a_destination_holds_then_backs_up_into_it(
    *,
    client: TestClient,
    workspace_root: Path,
    storage: Path,
    restic: InMemoryRestic,
    tmp_path: Path,
) -> None:
    cloud = _copy(tmp_path / "cloud" / "backups", "first", "second").root
    before = identities(cloud)
    copied = _without_locks(files(cloud))
    first_backup = _FirstBackup(storage)
    restic.on_start = first_backup.started

    status = _ok(_set_up(client, storage, [cloud]))

    assert status["connected"] == {"destination": str(cloud), "snapshots": 1}
    settings = (workspace_root / "settings.yaml").read_text(encoding="utf-8")
    assert f"repository: {storage}" in settings
    assert str(cloud) in settings
    # A fresh workspace gets its own ID, even when it connects a backup.
    assert "workspace_id: " in settings
    assert PASSWORD in (workspace_root / layout.ENV_FILE).read_text(encoding="utf-8")
    # The schedule backs up into the connected repository, and the copy back
    # only adds the new snapshot: nothing that was there is replaced or deleted.
    # The schedule starts the first backup as soon as the connect is done,
    # so the storage folder is read as connected when that backup begins.
    wait_for(lambda: len(_history(client)) == 1)
    assert first_backup.storage_as_connected == copied
    (entry,) = _history(client)
    assert entry["run"]["outcome"] == "succeeded", entry
    assert restic.ran("init") == 0
    after = identities(cloud)
    assert {name: after.get(name) for name in before} == before
    assert set(after) - set(before) == {f"snapshots/{_NEW_SNAPSHOT}"}


_NEW_SNAPSHOT = hashlib.sha256(b"snapshot made here").hexdigest()


class _FirstBackup:
    """An ``on_start`` that gives each backup a file, as restic would, and
    keeps the storage folder's files as they were before the first one."""

    def __init__(self, storage: Path) -> None:
        self.storage = storage
        self.storage_as_connected: dict[str, bytes] | None = None

    def started(self, operation: str) -> None:
        if operation != "back_up":
            return
        if self.storage_as_connected is None:
            self.storage_as_connected = _without_locks(files(self.storage))
        (self.storage / "snapshots" / _NEW_SNAPSHOT).write_bytes(b"snapshot made here")


def test_while_it_copies_the_status_says_it_is_connecting_from_the_destination(
    app: FastAPI, client: TestClient, storage: Path, restic: InMemoryRestic, tmp_path: Path
) -> None:
    cloud = _copy(tmp_path / "cloud", "first").root
    seen: list[dict[str, Any] | None] = []
    coordinator: BackupCoordinator = app.state.backups

    def started(operation: str) -> None:
        if operation == "verify_password":
            running = coordinator.running
            seen.append(None if running is None else running.model_dump())

    restic.on_start = started

    _ok(_set_up(client, storage, [cloud]))

    (running,) = seen
    assert running is not None
    assert (running["operation"], running["destination"]) == ("connect", str(cloud))


def test_a_password_that_does_not_open_the_backup_is_refused_on_the_password(
    client: TestClient, workspace_root: Path, storage: Path, restic: InMemoryRestic, tmp_path: Path
) -> None:
    cloud = _copy(tmp_path / "cloud", "first").root
    restic.password = "the old machine's password"
    before = _untouched(workspace_root, storage) | {"cloud": files(cloud)}

    refused = _set_up(client, storage, [cloud])

    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert f"{cloud} already holds a backup" in body["field_errors"]["password"]
    assert body["message"] == body["field_errors"]["password"]
    assert _untouched(workspace_root, storage) | {"cloud": files(cloud)} == before


def test_part_of_a_copy_without_config_is_refused(
    client: TestClient, workspace_root: Path, storage: Path, tmp_path: Path
) -> None:
    cloud = _copy(tmp_path / "cloud", "first")
    cloud.remove("config")
    before = _untouched(workspace_root, storage)

    refused = _set_up(client, storage, [cloud.root])

    assert refused.status_code == 422, refused.text
    assert "no config file" in refused.json()["message"]
    assert _untouched(workspace_root, storage) == before


def test_two_different_repositories_are_refused(
    client: TestClient, workspace_root: Path, storage: Path, tmp_path: Path
) -> None:
    icloud = _copy(tmp_path / "icloud", "first").root
    nas = _copy(tmp_path / "nas", "other", repository_id="another").root
    before = _untouched(workspace_root, storage)

    refused = _set_up(client, storage, [icloud, nas])

    assert refused.status_code == 422, refused.text
    assert "two different backup repositories" in refused.json()["message"]
    assert _untouched(workspace_root, storage) == before


def test_copies_that_each_lack_files_the_other_has_are_refused(
    client: TestClient, workspace_root: Path, storage: Path, tmp_path: Path
) -> None:
    icloud = _copy(tmp_path / "icloud", "first")
    nas = _copy(tmp_path / "nas", "first")
    icloud.backup("only in icloud")
    nas.backup("only on the nas")
    before = _untouched(workspace_root, storage)

    refused = _set_up(client, storage, [icloud.root, nas.root])

    assert refused.status_code == 422, refused.text
    assert "each has files the other lacks" in refused.json()["message"]
    assert _untouched(workspace_root, storage) == before


def test_of_several_copies_it_connects_the_complete_one_that_passes_a_check(
    *,
    client: TestClient,
    storage: Path,
    restic: InMemoryRestic,
    tmp_path: Path,
) -> None:
    """One copy still syncing (every file it has, the others have too) is
    never the source, so the copy back only adds to it; of the complete
    ones, the first to fail a check is passed over."""
    syncing = _copy(tmp_path / "icloud", "first").root
    failing = _copy(tmp_path / "nas", "first", "second").root
    passing = _copy(tmp_path / "usb", "first", "second").root
    checks: list[str] = []

    def started(operation: str) -> None:
        if operation == "check":
            checks.append(operation)
            if len(checks) == 1:
                raise ResticError("restic: pack is missing", exit_code=1)

    restic.on_start = started

    status = _ok(_set_up(client, storage, [syncing, failing, passing]))

    assert status["connected"]["destination"] == str(passing)
    assert len(checks) == 2
    wait_for(lambda: len(_history(client)) == 1)
    assert _without_locks(files(syncing)) == _without_locks(files(passing))


def test_a_storage_folder_that_holds_files_is_refused(
    client: TestClient, workspace_root: Path, storage: Path, tmp_path: Path
) -> None:
    cloud = _copy(tmp_path / "cloud", "first").root
    storage.mkdir()
    (storage / "notes.txt").write_text("mine", encoding="utf-8")
    before = _untouched(workspace_root, storage)

    refused = _set_up(client, storage, [cloud])

    assert refused.status_code == 409, refused.text
    assert "already holds files" in refused.json()["message"]
    assert _untouched(workspace_root, storage) == before


@pytest.mark.parametrize("destination", ["new", "empty"])
def test_with_no_backup_in_the_destinations_it_creates_one_as_before(
    *,
    client: TestClient,
    storage: Path,
    restic: InMemoryRestic,
    tmp_path: Path,
    destination: str,
) -> None:
    cloud = tmp_path / "cloud"
    if destination == "empty":
        cloud.mkdir()
    restic.snapshots.clear()

    status = _ok(_set_up(client, storage, [cloud]))

    assert status["connected"] is None
    assert restic.ran("init") == 1
    wait_for(lambda: len(_history(client)) == 1)
    assert (cloud / "config").is_file()


@pytest.mark.restic
def test_set_up_connects_a_real_repository_and_the_next_backup_adds_to_it(
    workspace_root: Path, tmp_path: Path, restic_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the pinned restic itself (plan, P3): a new machine whose iCloud
    Drive already holds the old machine's backups."""
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    old = tmp_path / "old-machine"
    configure_backups(workspace_root, old)
    workspace = Workspace.discover(root_override=workspace_root)
    home = tmp_path / "home"
    initialise(workspace, home)
    BackupRunner(workspace, ResticBinaries(home=home), home=home).run()
    cloud = tmp_path / "icloud"
    old.rename(cloud)
    (workspace_root / "settings.yaml").unlink()
    (workspace_root / layout.ENV_FILE).unlink()
    local = tmp_path / "local"

    with TestClient(create_app(workspace, backup=BackupEnvironment(home=home))) as client:
        wrong = _set_up(client, local, [cloud], password="not the password at all")
        status = _ok(_set_up(client, local, [cloud]))
        assert client.post("/api/backup/run").status_code == 202
        wait_for(lambda: len(_history(client)) == 1, timeout=120)
        (entry,) = _history(client)
        after = client.get("/api/backup").json()

    assert wrong.status_code == 422, wrong.text
    assert "password" in wrong.json()["field_errors"]
    assert status["connected"] == {"destination": str(cloud), "snapshots": 1}
    assert entry["run"]["outcome"] == "succeeded", entry
    assert after["repository"]["snapshots"] == 2

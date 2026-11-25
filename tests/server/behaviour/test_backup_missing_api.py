"""A missing or foreign backup repository, and the two ways back: create a
new one, or connect an existing one (workspace-backup spec, *Missing
repository*; plan, PR 8). Through the app with its lifespan running;
restic is the by-command fake unless a test is marked ``restic``, and every
folder is under ``tmp_path`` (plan, P2).

These check status codes and the answer's shape. What provisioning refuses,
its order, and that a refusal or failure leaves nothing behind are
``tests/core/behaviour/test_backup_provisioning.py``'s.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.application.backup_coordinator import BackupEnvironment
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import wait_for
from tests.support.backups import PASSWORD, configure_backups, initialise
from tests.support.repository_files import FakeRepository
from tests.support.restic import InMemoryRestic

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(tmp_path / "restic"))


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def restic() -> InMemoryRestic:
    return InMemoryRestic(lambda: NOW)


def _configure(workspace_root: Path, repository: Path, *, password: bool = True) -> None:
    configure_backups(workspace_root, repository, password=PASSWORD if password else None)


@pytest.fixture
def client(workspace_root: Path, tmp_path: Path, restic: InMemoryRestic) -> Iterator[TestClient]:
    environment = BackupEnvironment(home=tmp_path / "home", restic=restic, now=lambda: NOW)
    workspace = Workspace.discover(root_override=workspace_root)
    with TestClient(create_app(workspace, backup=environment)) as test_client:
        yield test_client


def _ok(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def _revision(client: TestClient) -> str:
    revision: str = _ok(client.get("/api/admin/settings"))["revision"]
    return revision


def _create(client: TestClient, repository: Path, password: str | None = None) -> Any:
    body = {"revision": _revision(client), "repository": str(repository), "password": password}
    return client.post("/api/backup/repository", json=body)


def _connect(
    client: TestClient, source: Path, repository: Path, password: str | None = None
) -> Any:
    body = {
        "revision": _revision(client),
        "source": str(source),
        "repository": str(repository),
        "password": password,
    }
    return client.post("/api/backup/connect", json=body)


def _kinds(client: TestClient) -> list[str]:
    return [w["kind"] for w in _ok(client.get("/api/backup"))["warnings"]]


@pytest.mark.parametrize("folder", ["missing", "foreign"])
def test_a_missing_or_foreign_repository_stops_backups_and_warns(
    workspace_root: Path,
    repository: Path,
    restic: InMemoryRestic,
    tmp_path: Path,
    folder: str,
) -> None:
    if folder == "foreign":
        repository.mkdir()
        (repository / "holiday.jpg").write_bytes(b"not restic")
    _configure(workspace_root, repository)
    environment = BackupEnvironment(home=tmp_path / "home", restic=restic, now=lambda: NOW)
    workspace = Workspace.discover(root_override=workspace_root)

    with TestClient(create_app(workspace, backup=environment)) as client:
        status = _ok(client.get("/api/backup"))
        refused = client.post("/api/backup/run")

    (warning,) = status["warnings"]
    assert warning["kind"] == "repository_missing"
    assert f"Backup repository not found at {repository}" in warning["message"]
    assert (status["repository"]["missing"], status["repository"]["password_stored"]) == (
        True,
        True,
    )
    assert status["next_due"] is None
    assert refused.status_code == 409
    assert restic.ran("back_up") == 0


def test_create_refuses_a_folder_that_holds_files(
    workspace_root: Path, repository: Path, client: TestClient, tmp_path: Path
) -> None:
    _configure(workspace_root, repository)
    elsewhere = tmp_path / "pictures"
    elsewhere.mkdir()
    (elsewhere / "holiday.jpg").write_bytes(b"mine")

    refused = _create(client, elsewhere)

    assert refused.status_code == 409, refused.text
    assert refused.json()["kind"] == "conflict"
    assert "already holds files" in refused.json()["message"]


def test_create_refused_while_a_destination_holds_a_repository_names_it(
    workspace_root: Path, repository: Path, client: TestClient, tmp_path: Path
) -> None:
    """The refusal carries ``connect_from``, so the page offers Connect."""
    cloud = tmp_path / "cloud"
    (cloud / "keys").mkdir(parents=True)
    _configure(workspace_root, repository)
    settings = workspace_root / "settings.yaml"
    with settings.open("a", encoding="utf-8") as appended:
        appended.write(f"  destinations:\n    - {cloud.as_posix()}\n")

    refused = _create(client, repository)

    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert str(cloud) in body["message"]
    assert body["connect_from"] == str(cloud)


def test_create_checks_the_revision_even_when_using_the_saved_path(
    workspace_root: Path, repository: Path, client: TestClient
) -> None:
    _configure(workspace_root, repository)
    old_revision = _revision(client)
    with (workspace_root / "settings.yaml").open("a", encoding="utf-8") as settings:
        settings.write("  interval_hours: 6\n")

    response = client.post(
        "/api/backup/repository", json={"revision": old_revision, "repository": str(repository)}
    )

    assert response.status_code == 412, response.text
    assert response.json()["kind"] == "stale"


def test_create_at_a_confirmed_folder_saves_it_and_starts_backing_up(
    workspace_root: Path, repository: Path, client: TestClient, tmp_path: Path
) -> None:
    _configure(workspace_root, repository)
    chosen = tmp_path / "new-backups"

    _ok(_create(client, chosen), 202)

    assert (chosen / "config").is_file()
    assert f"repository: {chosen}" in (workspace_root / "settings.yaml").read_text("utf-8")
    wait_for(lambda: _ok(client.get("/api/backup"))["last_success"] is not None)
    assert _kinds(client) == []


def test_create_asks_for_a_password_only_when_none_is_stored(
    workspace_root: Path, repository: Path, client: TestClient
) -> None:
    _configure(workspace_root, repository, password=False)
    assert _ok(client.get("/api/backup"))["repository"]["password_stored"] is False

    needed = _create(client, repository)
    short = _create(client, repository, "short")
    _ok(_create(client, repository, PASSWORD), 202)

    assert needed.status_code == 422, needed.text
    assert "password" in needed.json()["message"].lower()
    assert short.status_code == 422
    assert _ok(client.get("/api/backup"))["repository"]["password_stored"] is True


def _destination_copy(tmp_path: Path) -> Path:
    """A destination copy, as restored onto a new machine."""
    cloud = tmp_path / "cloud" / "backups"
    FakeRepository(cloud).backup("first")
    return cloud


def test_connect_copies_the_repository_to_local_disk_then_opens_it(
    workspace_root: Path,
    repository: Path,
    client: TestClient,
    restic: InMemoryRestic,
    tmp_path: Path,
) -> None:
    _configure(workspace_root, repository, password=False)
    cloud = _destination_copy(tmp_path)
    restic.password = PASSWORD
    restic.snapshots.append(NOW)
    chosen = tmp_path / "local-backups"

    status = _ok(_connect(client, cloud, chosen, PASSWORD))

    assert status["repository"]["path"] == str(chosen)
    assert status["repository"]["password_stored"] is True
    assert status["warnings"] == []


def test_a_wrong_password_is_a_422_and_the_repository_stays_missing(
    workspace_root: Path,
    repository: Path,
    client: TestClient,
    restic: InMemoryRestic,
    tmp_path: Path,
) -> None:
    _configure(workspace_root, repository, password=False)
    cloud = _destination_copy(tmp_path)
    restic.password = "the old machine's password"

    refused = _connect(client, cloud, repository, PASSWORD)

    assert refused.status_code == 422, refused.text
    assert refused.json()["kind"] == "invalid"
    assert "password" in refused.json()["message"].lower()
    assert _kinds(client) == ["repository_missing"]


def test_connect_refuses_a_folder_that_is_not_a_repository_or_a_full_target(
    workspace_root: Path, repository: Path, client: TestClient, tmp_path: Path
) -> None:
    _configure(workspace_root, repository)
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    (pictures / "holiday.jpg").write_bytes(b"mine")
    cloud = _destination_copy(tmp_path)

    not_restic = _connect(client, pictures, repository)
    full = _connect(client, cloud, pictures)

    assert not_restic.status_code == 422, not_restic.text
    assert "not a restic repository" in not_restic.json()["message"]
    assert full.status_code == 409, full.text
    assert not repository.exists()


def test_create_and_connect_are_refused_while_the_repository_is_there(
    workspace_root: Path, repository: Path, client: TestClient, tmp_path: Path
) -> None:
    _configure(workspace_root, repository)
    FakeRepository(repository)

    assert _create(client, tmp_path / "new").status_code == 409
    assert _connect(client, _destination_copy(tmp_path), tmp_path / "new").status_code == 409


@pytest.mark.restic
def test_connect_copies_then_opens_a_repository_restic_made(
    workspace_root: Path, tmp_path: Path, restic_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the pinned restic itself (plan, P3): a destination copy of a
    real repository, connected on a "new machine" whose own is gone."""
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    old = tmp_path / "old-machine"
    _configure(workspace_root, old)
    workspace = Workspace.discover(root_override=workspace_root)
    home = tmp_path / "home"
    initialise(workspace, home)
    record = BackupRunner(workspace, ResticBinaries(home=home), home=home).run()
    cloud = tmp_path / "cloud"
    old.rename(cloud)
    (workspace_root / layout.ENV_FILE).unlink()
    local = tmp_path / "local"

    with TestClient(create_app(workspace, backup=BackupEnvironment(home=home))) as client:
        assert _kinds(client) == ["repository_missing"]
        wrong = _connect(client, cloud, local, "not the password at all")
        status = _ok(_connect(client, cloud, local, PASSWORD))

    assert wrong.status_code == 422, wrong.text
    assert status["repository"]["snapshots"] == 1
    assert status["last_success"] is not None
    assert record.snapshot_id is not None
    assert (local / "snapshots" / record.snapshot_id).is_file()

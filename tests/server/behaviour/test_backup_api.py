"""The backup endpoints under ``/api/backup`` and the Setup save through
Admin settings (workspace-backup plan, PR 5), through the app with its
lifespan running, so the scheduler is live beside each request. restic is
the by-command fake unless a test is marked ``restic``; ``home`` is under
``tmp_path`` throughout (plan, P2).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.application.backup_coordinator import BackupEnvironment
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR
from etsy_listings.core.backup.state import (
    BackupState,
    BackupStateStore,
    CheckResult,
    DestinationState,
)
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import wait_for
from tests.support.repository_files import FakeRepository, files
from tests.support.restic import RepositoryRestic

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    # Named, so set-up never downloads restic; the fake launcher ignores it.
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(tmp_path / "restic"))


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def restic(repository: Path) -> RepositoryRestic:
    return RepositoryRestic(repository, lambda: NOW)


def _client(workspace_root: Path, home: Path, restic: RepositoryRestic | None) -> TestClient:
    environment = BackupEnvironment(home=home, launch=restic, now=lambda: NOW)
    workspace = Workspace.discover(root_override=workspace_root)
    return TestClient(create_app(workspace, backup=environment))


@pytest.fixture
def client(workspace_root: Path, home: Path, restic: RepositoryRestic) -> Iterator[TestClient]:
    with _client(workspace_root, home, restic) as test_client:
        yield test_client


def _ok(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def _set_up(client: TestClient, repository: Path, **override: object) -> Any:
    revision = _ok(client.get("/api/admin/settings"))["revision"]
    body = {
        "revision": revision,
        "repository": str(repository),
        "destinations": [],
        "interval_hours": 12,
        "retention": {"keep_within_days": 7, "weekly": 4, "monthly": 3},
        "password": PASSWORD,
    } | override
    return client.post("/api/backup/setup", json=body)


def _history(client: TestClient) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = _ok(client.get("/api/backup/history"))["runs"]
    return runs


def test_backups_are_off_until_set_up(client: TestClient) -> None:
    status = _ok(client.get("/api/backup"))

    assert status["enabled"] is False
    assert [(w["kind"], w["banner"]) for w in status["warnings"]] == [("off", False)]
    assert _history(client) == []


def test_set_up_writes_the_block_and_password_then_starts_the_first_backup(
    client: TestClient, workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    cloud = tmp_path / "cloud" / "backups"
    cloud.parent.mkdir()

    status = _ok(_set_up(client, repository, destinations=[str(cloud)], interval_hours=6), 202)

    assert status["enabled"] is True
    wait_for(lambda: len(_history(client)) == 1)
    (entry,) = _history(client)
    assert (entry["run"]["outcome"], entry["kept_as"]) == ("succeeded", "recent")
    settings = workspace_root.joinpath("settings.yaml").read_text(encoding="utf-8")
    assert "interval_hours: 6" in settings
    assert str(repository) in settings
    assert PASSWORD in (workspace_root / layout.ENV_FILE).read_text(encoding="utf-8")
    assert (repository / "config").is_file()
    assert files(cloud).keys() == files(repository).keys()
    status = _ok(client.get("/api/backup"))
    assert status["last_success"] is not None
    assert status["warnings"] == []
    assert status["destinations"][0]["path"] == str(cloud)


def test_set_up_refuses_a_password_under_12_characters(
    client: TestClient, workspace_root: Path, repository: Path
) -> None:
    refused = _set_up(client, repository, password="short")

    assert refused.status_code == 422, refused.text
    assert "12 characters" in refused.json()["message"]
    assert not workspace_root.joinpath("settings.yaml").exists()
    assert not repository.exists()


def test_set_up_refuses_a_folder_that_holds_files(
    client: TestClient, workspace_root: Path, repository: Path
) -> None:
    repository.mkdir()
    (repository / "notes.txt").write_text("mine", encoding="utf-8")

    refused = _set_up(client, repository)

    assert refused.status_code == 409, refused.text
    assert "already holds files" in refused.json()["message"]
    assert not workspace_root.joinpath("settings.yaml").exists()


def test_set_up_refuses_a_destination_whose_drive_is_missing(
    client: TestClient, workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    offline = tmp_path / "offline-drive" / "backups"

    refused = _set_up(client, repository, destinations=[str(offline)])

    assert refused.status_code == 422, refused.text
    assert "backup.destinations" in refused.json()["field_errors"]
    assert not workspace_root.joinpath("settings.yaml").exists()


def test_set_up_twice_is_refused(
    client: TestClient, workspace_root: Path, repository: Path, tmp_path: Path
) -> None:
    _ok(_set_up(client, repository), 202)
    before = (workspace_root / "settings.yaml").read_bytes()

    refused = _set_up(client, tmp_path / "elsewhere")

    assert refused.status_code == 409, refused.text
    assert "already set up" in refused.json()["message"]
    assert (workspace_root / "settings.yaml").read_bytes() == before


def test_back_up_now_starts_a_run_and_refuses_a_second(
    client: TestClient, restic: RepositoryRestic, repository: Path
) -> None:
    restic.hang = True
    _ok(_set_up(client, repository), 202)
    wait_for(lambda: restic.ran("backup") == 1)

    assert _ok(client.get("/api/backup"))["running"]["operation"] == "backup"
    assert client.post("/api/backup/run").status_code == 409


def test_back_up_now_is_refused_while_backups_are_off(client: TestClient) -> None:
    assert client.post("/api/backup/run").status_code == 409


def _configured(workspace_root: Path, repository: Path, *destinations: Path) -> None:
    listed = "".join(f"    - {path.as_posix()}\n" for path in destinations)
    workspace_root.joinpath("settings.yaml").write_text(
        f"backup:\n  repository: {repository.as_posix()}\n"
        + (f"  destinations:\n{listed}" if destinations else ""),
        encoding="utf-8",
    )
    (workspace_root / layout.ENV_FILE).write_text(f"{BACKUP_PASSWORD_VAR}={PASSWORD}\n")


def test_repair_sets_aside_unexpected_files_and_clears_the_warning(
    workspace_root: Path, home: Path, repository: Path, tmp_path: Path
) -> None:
    local = FakeRepository(repository)
    local.backup("first")
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    (cloud / "index").mkdir()
    (cloud / "index" / "a3f9 2").write_bytes(b"conflict copy")
    _configured(workspace_root, repository, cloud)
    found = DestinationState(last_copy=NOW, unexpected=("index/a3f9 2",))
    BackupStateStore(home).save(
        BackupState(
            repository=str(repository),
            last_prune=NOW,
            last_check=CheckResult(at=NOW, ok=True),
            destinations={str(cloud): found},
        )
    )
    restic = RepositoryRestic(repository, lambda: NOW)
    restic.snapshots.append(NOW)

    # An earlier repair the same day: this one takes the next name.
    taken = cloud.with_name(f"cloud-set-aside-{NOW.astimezone().date().isoformat()}")
    taken.mkdir()

    with _client(workspace_root, home, restic) as client:
        status = _ok(client.get("/api/backup"))
        assert [w["kind"] for w in status["warnings"]] == ["changed"]
        planned = _destinations(status)[0]["set_aside"]

        repaired = _ok(client.post("/api/backup/repair", json={"destination": str(cloud)}))

        assert repaired["moved"] == ["index/a3f9 2"]
        assert repaired["outcome"] == "copied"
        assert repaired["set_aside"] == planned == f"{taken}-2"
        assert _ok(client.get("/api/backup"))["warnings"] == []
        unknown = client.post("/api/backup/repair", json={"destination": str(tmp_path / "x")})
        assert unknown.status_code == 404


COMMENTED = """\
# The seller's own notes stay put.
backup:
  repository: {repository}
  destinations:
    - {first}  # the iCloud copy
    - {second}  # the old NAS
  interval_hours: 12  # twice a day
"""


def _save(client: TestClient, **changes: object) -> Any:
    revision = _ok(client.get("/api/admin/settings"))["revision"]
    return client.patch("/api/admin/settings", json={"revision": revision, "changes": changes})


def test_a_setup_save_keeps_the_comments_and_creates_an_added_destination(
    workspace_root: Path, home: Path, repository: Path, tmp_path: Path
) -> None:
    first, second, third = (tmp_path / name for name in ("icloud", "nas", "usb"))
    first.mkdir()
    second.mkdir()
    path = workspace_root / "settings.yaml"
    path.write_text(
        COMMENTED.format(repository=repository, first=first, second=second), encoding="utf-8"
    )

    with _client(workspace_root, home, None) as client:
        assert _ok(client.get("/api/admin/settings"))["backup"]["interval_hours"] == 12
        saved = _save(
            client,
            backup_destinations=[str(first), str(third)],
            backup_interval_hours=6,
            backup_retention={"keep_within_days": 7, "weekly": 8, "monthly": 3},
        )

    body = _ok(saved)
    assert body["backup"]["destinations"] == [str(first), str(third)]
    assert third.is_dir()
    text = path.read_text(encoding="utf-8")
    assert "# The seller's own notes stay put." in text
    assert f"{first}  # the iCloud copy" in text
    assert "the old NAS" not in text
    assert "interval_hours: 6  # twice a day" in text
    assert "weekly: 8" in text


def test_a_setup_save_refuses_a_destination_whose_drive_is_missing(
    workspace_root: Path, home: Path, repository: Path, tmp_path: Path
) -> None:
    _configured(workspace_root, repository)
    before = (workspace_root / "settings.yaml").read_bytes()

    with _client(workspace_root, home, None) as client:
        refused = _save(client, backup_destinations=[str(tmp_path / "offline" / "backups")])
        repository_edit = _save(client, backup_repository=str(tmp_path / "elsewhere"))

    assert refused.status_code == 422, refused.text
    assert "does not exist" in refused.json()["field_errors"]["backup.destinations"]
    assert repository_edit.status_code == 422
    assert (workspace_root / "settings.yaml").read_bytes() == before


def test_a_setup_save_refuses_a_destination_that_is_a_file(
    workspace_root: Path, home: Path, repository: Path, tmp_path: Path
) -> None:
    _configured(workspace_root, repository)
    settings = workspace_root / "settings.yaml"
    before = settings.read_bytes()
    existing = tmp_path / "file"
    existing.write_bytes(b"keep me")

    with _client(workspace_root, home, None) as client:
        refused = _save(client, backup_destinations=[str(existing)])

    assert refused.status_code == 422, refused.text
    assert settings.read_bytes() == before
    assert existing.read_bytes() == b"keep me"


@pytest.mark.restic
def test_set_up_with_restic_makes_a_first_backup_the_history_shows(
    workspace_root: Path, home: Path, repository: Path, restic_binary: Path
) -> None:
    """With the pinned restic itself (plan, P3)."""
    workspace = Workspace.discover(root_override=workspace_root)
    app = create_app(workspace, backup=BackupEnvironment(home=home))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
        with TestClient(app) as client:
            _ok(_set_up(client, repository), 202)
            wait_for(lambda: len(_history(client)) == 1, timeout=120)
            (entry,) = _history(client)
            status = _ok(client.get("/api/backup"))

    assert entry["run"]["outcome"] == "succeeded", entry
    assert entry["kept_as"] == "recent"
    assert status["repository"]["snapshots"] == 1


def test_a_destination_folder_gone_missing_is_reported_and_never_created(
    workspace_root: Path, home: Path, repository: Path, tmp_path: Path
) -> None:
    """Only set-up and a Setup save create a destination (PR 4's finish): a
    run reports the missing folder and leaves its parent alone."""
    FakeRepository(repository).backup("first")
    signed_out = tmp_path / "iCloudDrive" / "backups"
    signed_out.parent.mkdir()
    _configured(workspace_root, repository, signed_out)
    BackupStateStore(home).save(BackupState(repository=str(repository), last_prune=NOW))
    restic = RepositoryRestic(repository, lambda: NOW)

    with _client(workspace_root, home, restic) as client:
        wait_for(lambda: len(_history(client)) == 1)
        status = _ok(client.get("/api/backup"))

    (entry,) = _destinations(status)
    assert entry["problem"].startswith("Folder not found")
    assert entry["last_copy"] is None
    assert not signed_out.exists()


def _destinations(status: dict[str, Any]) -> list[dict[str, Any]]:
    destinations: list[dict[str, Any]] = status["destinations"]
    return destinations


@pytest.fixture
def restorable(
    workspace_root: Path, home: Path, repository: Path, restic: RepositoryRestic
) -> Iterator[TestClient]:
    """Set up, with one snapshot made by the app and one by hand."""
    _configured(workspace_root, repository)
    repository.mkdir()
    (repository / "config").write_bytes(b"{}")
    restic.snapshots += [NOW - timedelta(days=1), NOW - timedelta(hours=1)]
    with _client(workspace_root, home, restic) as test_client:
        yield test_client


def test_the_snapshot_list_is_restic_s_own_newest_first(
    restorable: TestClient, workspace_root: Path, home: Path
) -> None:
    listed = _ok(restorable.get("/api/backup/snapshots"))

    assert listed["workspace"] == str(workspace_root)
    assert [s["id"] for s in listed["snapshots"]] == [f"{2:064x}", f"{1:064x}"]
    newest = listed["snapshots"][0]
    restored = workspace_root.with_name(f"{workspace_root.name}-restore-{newest['short_id']}")
    assert newest["restore_target"] == str(restored)
    assert BackupStateStore(home).runs() == [], "no run recorded either snapshot"


def test_a_restore_starts_shows_in_the_status_and_stops(
    restorable: TestClient, restic: RepositoryRestic, tmp_path: Path
) -> None:
    restic.restore_hang = True
    target = str(tmp_path / "restored")

    started = _ok(
        restorable.post("/api/backup/restore", json={"snapshot": f"{1:064x}", "target": target}),
        202,
    )
    wait_for(lambda: _ok(restorable.get("/api/backup"))["restore"]["files_done"] == 100)
    second = restorable.post("/api/backup/restore", json={"snapshot": "latest", "target": target})
    stopped = _ok(restorable.post("/api/backup/restore/stop"))

    assert (started["restore"]["outcome"], started["restore"]["target"]) == ("running", target)
    assert second.status_code == 409
    assert stopped["restore"]["outcome"] == "stopped"


@pytest.mark.parametrize("case", [("workspace", 409), ("relative", 422), ("unknown", 404)])
def test_a_restore_is_refused_before_restic_runs(
    restorable: TestClient,
    restic: RepositoryRestic,
    workspace_root: Path,
    tmp_path: Path,
    case: tuple[str, int],
) -> None:
    target, status = case
    body = {
        "workspace": {"snapshot": "latest", "target": str(workspace_root)},
        "relative": {"snapshot": "latest", "target": "restored"},
        "unknown": {"snapshot": "beef", "target": str(tmp_path / "restored")},
    }[target]

    response = restorable.post("/api/backup/restore", json=body)

    assert response.status_code == status, response.text
    assert restic.ran("restore") == 0

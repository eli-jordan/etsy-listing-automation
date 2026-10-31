"""Settings HTTP contract over real revision-checked fixture files (Admin PR 4)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app


@pytest.fixture
def client(workspace_root: Path) -> TestClient:
    return TestClient(create_app(Workspace.discover(root_override=workspace_root)))


def test_missing_settings_are_defaults_until_a_save(
    client: TestClient, workspace_root: Path
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    body = client.get("/api/admin/settings").json()
    assert body["concurrency"] == 1
    assert (
        body["weights"]
        == body["default_weights"]
        == {
            "reviews": 30,
            "favourites_per_day": 30,
            "search_rank": 20,
            "views_per_day": 10,
            "shop_sales": 5,
            "shop_rating": 5,
        }
    )
    assert not path.exists()
    saved = client.patch(
        "/api/admin/settings", json={"revision": body["revision"], "changes": {"concurrency": 3}}
    )
    assert saved.status_code == 200
    assert saved.json()["concurrency"] == 3
    assert saved.json()["revision"] != body["revision"]
    assert client.get("/api/admin/settings").json() == saved.json()


def test_invalid_patch_and_external_comment_are_refused(
    client: TestClient, workspace_root: Path
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_bytes(b"batch_ai:\n  concurrency: 2\n")
    revision = client.get("/api/admin/settings").json()["revision"]
    original = path.read_bytes()
    refused = client.patch(
        "/api/admin/settings", json={"revision": revision, "changes": {"concurrency": 9}}
    )
    assert refused.status_code == 422
    assert "batch_ai.concurrency" in refused.json()["field_errors"]
    assert path.read_bytes() == original
    path.write_bytes(original + b"# external edit\n")
    conflict = client.patch(
        "/api/admin/settings", json={"revision": revision, "changes": {"concurrency": 3}}
    )
    assert conflict.status_code == 409
    assert conflict.json()["kind"] == "conflict"
    assert path.read_bytes() == original + b"# external edit\n"


def test_invalid_file_names_its_key_instead_of_returning_defaults(
    client: TestClient, workspace_root: Path
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_bytes(b"batch_ai:\n  concurency: 2\n")
    refused = client.get("/api/admin/settings")
    assert refused.status_code == 422
    assert "settings.yaml" in refused.json()["detail"]
    assert "batch_ai.concurency" in refused.json()["detail"]


def test_provider_rows_include_omitted_providers_and_save_preferences(client: TestClient) -> None:
    initial = client.get("/api/admin/settings").json()
    assert [p["name"] for p in initial["providers"]] == ["codex", "claude", "grok"]
    saved = client.patch(
        "/api/admin/settings",
        json={
            "revision": initial["revision"],
            "changes": {"providers": [{"name": "grok", "model": "old", "effort": "high"}]},
        },
    )
    assert saved.status_code == 200
    assert [(p["name"], p["enabled"]) for p in saved.json()["providers"]] == [
        ("grok", True),
        ("codex", False),
        ("claude", False),
    ]
    assert saved.json()["providers"][0]["model"] == "old"


def test_model_discovery_reads_and_refreshes_without_changing_settings(client: TestClient) -> None:
    from etsy_listings.core.ai.discovery import ModelCatalogs

    class Discovery:
        def __init__(self):
            self.refreshes = []

        def read(self, *, refresh=False):
            self.refreshes.append(refresh)
            return ModelCatalogs()

    discovery = Discovery()
    client.app.state.model_discovery = discovery
    before = client.get("/api/admin/settings").json()
    assert client.get("/api/admin/settings/models").status_code == 200
    assert client.get("/api/admin/settings/models?refresh=true").status_code == 200
    assert discovery.refreshes == [False, True]
    assert client.get("/api/admin/settings").json() == before


def test_startup_attempts_discovery_without_changing_preferences(workspace_root: Path) -> None:
    from etsy_listings.core.ai.discovery import ModelCatalogs, ModelDiscovery

    class Discovery(ModelDiscovery):
        attempted = False

        def read(self, *, refresh=False):
            self.attempted = True
            return ModelCatalogs()

    discovery = Discovery()
    workspace = Workspace.discover(root_override=workspace_root)
    with TestClient(create_app(workspace, model_discovery=discovery)):
        assert discovery.attempted
    assert not workspace.settings_file().exists()

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


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_http_provider_reorder_without_final_newline(
    client: TestClient, workspace_root: Path, newline: bytes
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_bytes(
        b"# preferences\nai:\n  providers:\n  - name: codex\n  - name: grok".replace(b"\n", newline)
    )
    initial = client.get("/api/admin/settings").json()
    saved = client.patch(
        "/api/admin/settings",
        json={
            "revision": initial["revision"],
            "changes": {"providers": [{"name": "grok"}, {"name": "claude"}, {"name": "codex"}]},
        },
    )
    assert saved.status_code == 200
    assert client.get("/api/admin/settings").json() == saved.json()
    assert path.read_bytes() == (
        b"# preferences\nai:\n  providers:\n  - name: grok\n  - name: claude\n  - name: codex"
    ).replace(b"\n", newline)


@pytest.mark.parametrize(
    "source",
    [
        b"ai:\n  providers: [{<<: {name: codex}, model: old}]\n",
        b"ai:\n  providers:\n  - name: codex\n    model: &shared old\n    effort: *shared\n",
    ],
)
def test_unsupported_yaml_edit_is_an_actionable_refusal_and_keeps_source(
    client: TestClient, workspace_root: Path, source: bytes
) -> None:
    path = Workspace.discover(root_override=workspace_root).settings_file()
    path.write_bytes(source)
    initial = client.get("/api/admin/settings").json()
    saved = client.patch(
        "/api/admin/settings",
        json={
            "revision": initial["revision"],
            "changes": {
                "providers": [
                    {"name": "codex", "model": "new", "effort": initial["providers"][0]["effort"]}
                ]
            },
        },
    )
    assert saved.status_code == 422
    assert saved.json()["kind"] == "invalid"
    assert "settings.yaml" in saved.json()["message"]
    assert "edit" in saved.json()["message"].lower()
    assert "__root__" in saved.json()["field_errors"]
    assert path.read_bytes() == source


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


def test_time_limits_read_save_together_and_refuse_a_run_below_the_floor(
    client: TestClient, workspace_root: Path
) -> None:
    """ADR-0057 over HTTP: defaults, the coupled save, and the floor refusal."""
    path = Workspace.discover(root_override=workspace_root).settings_file()
    initial = client.get("/api/admin/settings").json()
    assert (initial["step_limit_minutes"], initial["run_limit_minutes"]) == (5, 20)

    refused = client.patch(
        "/api/admin/settings",
        json={"revision": initial["revision"], "changes": {"step_limit_minutes": 10}},
    )
    assert refused.status_code == 422
    assert "at least 30" in refused.json()["field_errors"]["ai.run_limit_minutes"]
    assert not path.exists()

    saved = client.patch(
        "/api/admin/settings",
        json={
            "revision": initial["revision"],
            "changes": {"step_limit_minutes": 10, "run_limit_minutes": 30},
        },
    )
    assert saved.status_code == 200
    assert (saved.json()["step_limit_minutes"], saved.json()["run_limit_minutes"]) == (10, 30)
    assert path.read_text() == "ai:\n  step_limit_minutes: 10\n  run_limit_minutes: 30\n"

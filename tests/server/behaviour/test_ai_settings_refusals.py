"""Invalid saved settings refuse public AI workflows before generation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import ChainProvider, seed_prompts
from tests.support.batches import LISTING_TEMPLATE, a_listing_template, png


@pytest.fixture
def configured(workspace_root: Path):
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)
    provider = ChainProvider()
    app = create_app(workspace, seo_provider_factory=lambda _workspace, _ai: [provider])
    return workspace, provider, TestClient(app)


@pytest.mark.parametrize(
    "source,key",
    [
        (b"ai:\n  step_limit_minutes: 99\n", "ai.step_limit_minutes"),
        (b"ai:\n  run_limit_minutes: 5\n", "ai.run_limit_minutes"),
        (b"ai:\n  providers: []\n", "ai.providers"),
        (b"ai: [\n", "not valid YAML"),
    ],
)
def test_invalid_settings_disable_readiness_and_refuse_run_without_starting(
    configured, source: bytes, key: str
) -> None:
    workspace, provider, client = configured
    assert client.get("/api/listings/take-a-hike/ai-seo/readiness").json()["ready"]
    workspace.settings_file().write_bytes(source)

    admin = client.get("/api/admin/settings")
    assert admin.status_code == 422
    ready = client.get("/api/listings/take-a-hike/ai-seo/readiness")
    assert ready.status_code == 200
    assert ready.json()["ready"] is False
    refused = client.post("/api/ai/runs", json={"listing": "take-a-hike", "draft_brief": True})
    assert refused.status_code == 409
    assert refused.json()["reason"] == ready.json()["reason"]
    assert key in refused.json()["reason"]
    assert "settings.yaml" in refused.json()["reason"]
    assert client.get("/api/ai/runs?listing=take-a-hike").status_code == 404
    assert provider.calls == []
    assert workspace.settings_file().read_bytes() == source


def test_a_provider_factory_defect_is_not_disguised_as_invalid_settings(
    workspace_root: Path,
) -> None:
    seed_prompts(workspace_root)
    workspace = Workspace.discover(root_override=workspace_root)

    def broken_factory(_workspace, _ai):
        raise RuntimeError("provider factory defect")

    client = TestClient(create_app(workspace, seo_provider_factory=broken_factory))
    with pytest.raises(RuntimeError, match="provider factory defect"):
        client.get("/api/listings/take-a-hike/ai-seo/readiness")


def test_invalid_settings_keep_staging_and_explain_batch_readiness(configured) -> None:
    workspace, provider, client = configured
    a_listing_template(workspace)
    source = b"ai:\n  step_limit_minutes: 99\n"
    workspace.settings_file().write_bytes(source)
    blocked = client.app.state.ai.queue.blocked()
    assert blocked is not None
    assert "settings.yaml" in blocked.message
    assert "ai.step_limit_minutes" in blocked.message
    assert "staging is kept" in blocked.remedy

    staged = client.post(
        "/api/staging",
        data={"listing_template": LISTING_TEMPLATE},
        files=[("files", ("hike.png", png(1), "image/png"))],
    )
    assert staged.status_code == 200
    body = staged.json()
    assert body["ai_blocked"] == blocked.model_dump()
    assert client.get(f"/api/staging/{body['id']}").json() == body
    refused = client.post(f"/api/staging/{body['id']}/confirm")
    assert refused.status_code == 409
    assert "ai.step_limit_minutes" in refused.text
    assert client.get(f"/api/staging/{body['id']}").status_code == 200
    assert not workspace.batch_ids()
    assert provider.calls == []


def test_invalid_settings_explain_existing_batch_reads_and_controls(configured) -> None:
    workspace, provider, client = configured
    a_listing_template(workspace)
    staged = client.post(
        "/api/staging",
        data={"listing_template": LISTING_TEMPLATE},
        files=[("files", ("audit-design.png", png(1), "image/png"))],
    ).json()
    created = client.post(f"/api/staging/{staged['id']}/confirm")
    assert created.status_code == 200
    batch_id = created.json()["id"]
    workspace.settings_file().write_bytes(b"ai:\n  step_limit_minutes: 99\n")

    responses = [
        client.get(f"/api/batches/{batch_id}"),
        client.post(f"/api/batches/{batch_id}/cancel"),
        client.post(f"/api/batches/{batch_id}/resume"),
        client.patch(f"/api/batches/{batch_id}", json={"label": "Still kept"}),
    ]
    for response in responses:
        assert response.status_code == 422
        assert "settings.yaml" in response.json()["detail"]
        assert "ai.step_limit_minutes" in response.json()["detail"]
    assert provider.calls == []

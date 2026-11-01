"""Application availability and shutdown while advisory discovery is busy."""

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.ai.discovery import ModelDiscovery
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_processes import ModelCli
from tests.support.gates import GATE_TIMEOUT, Gate, workers


def test_startup_serves_health_while_advisory_discovery_is_blocked(
    workspace_root: Path, monkeypatch
) -> None:
    gate = Gate("discovery process")
    cli = ModelCli(during=lambda deadline, cancel: gate.hold())
    monkeypatch.setattr("etsy_listings.core.ai.discovery.shutil.which", lambda name: name)
    monkeypatch.setattr("etsy_listings.core.ai.discovery.run_managed", cli)
    discovery = ModelDiscovery()
    workspace = Workspace.discover(root_override=workspace_root)
    app = create_app(workspace, model_discovery=discovery)
    assert cli.calls == [], "construction must start no discovery"
    serving = threading.Event()
    health = []
    finish = Gate("server lifespan")

    def serve():
        with TestClient(app) as client:
            health.append(client.get("/api/health").json()["status"])
            serving.set()
            finish.hold()

    with workers(gate, finish) as start:
        server = start("server", serve)
        gate.wait_entered()
        assert serving.wait(3), "advisory discovery held application startup"
        assert health == ["ok"]
        gate.release()
        finish.release()
        server.result()
    assert not workspace.settings_file().exists()


def test_lifespan_shutdown_cancels_discovery_and_http_reads_keep_saved_preferences(
    workspace_root: Path, monkeypatch
) -> None:
    entered, stopped = threading.Event(), threading.Event()

    def until_cancelled(deadline, cancel):
        entered.set()
        assert cancel.wait(GATE_TIMEOUT), "lifespan did not cancel discovery"
        stopped.set()

    cli = ModelCli(during=until_cancelled)
    monkeypatch.setattr("etsy_listings.core.ai.discovery.shutil.which", lambda name: name)
    monkeypatch.setattr("etsy_listings.core.ai.discovery.run_managed", cli)
    workspace = Workspace.discover(root_override=workspace_root)
    source = b"ai:\n  providers: [{name: codex, model: saved-old-model}]\n"
    workspace.settings_file().write_bytes(source)
    with TestClient(create_app(workspace)) as client:
        assert entered.wait(GATE_TIMEOUT)
        initial = client.get("/api/admin/settings").json()
        for url in ("/api/admin/settings/models", "/api/admin/settings/models?refresh=true"):
            response = client.get(url)
            assert response.status_code == 200
            assert "in progress" in response.json()["providers"]["codex"]["problem"]
        assert client.get("/api/admin/settings").json() == initial
        assert initial["providers"][0]["model"] == "saved-old-model"
    assert stopped.is_set()
    assert len(cli.calls) == 1
    assert workspace.settings_file().read_bytes() == source

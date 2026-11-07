"""Settings limits and Marigold coverage over HTTP (template positions PR 7b;
spec *Rendering → Marigold (option B)*, *Limits changes*, *Recalibration*).

Widening the limits past a positioned Marigold template's evidence names it in
the confirmation's impact read and, once saved, queues its coverage inference.
Narrowing never does either.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.builders import edit_listing
from tests.support.marigold import PreparationRuntime, covered_small_print, marigold_template

SETTINGS = "/api/admin/settings"
IMPACT = "/api/admin/settings/template-positions/impact"
DEFAULTS = {"scale": {"min": 0.8, "max": 1.1}, "offset": 0.1, "rotation": 15}
WIDER = {**DEFAULTS, "rotation": 25}
NARROWER = {**DEFAULTS, "scale": {"min": 0.9, "max": 1.05}}


def _position(workspace: Workspace, template: str) -> dict[str, object]:
    box = compose(template_state(workspace, template).require().bounding_box, Pose(rotation=5))
    return {template: {"bounding_box": [point.model_dump() for point in box]}}


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    """``tee`` covered at the default limits and positioned by the fixture
    listing; ``shirt`` is Marigold, prepared nowhere and positioned by no one."""
    workspace = covered_small_print(workspace_root)
    marigold_template(workspace_root)
    edit_listing(
        workspace_root, media=[{"template": "tee"}], template_positions=_position(workspace, "tee")
    )
    return workspace


def test_impact_names_positioned_templates_only_when_the_limits_widen(workspace: Workspace):
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))

    def needing(limits: dict[str, object]) -> list[str]:
        response = client.post(IMPACT, json={"limits": limits})
        assert response.status_code == 200, response.text
        return response.json()["templates_needing_inference"]

    assert needing(WIDER) == ["tee"]
    assert needing(DEFAULTS) == []
    assert needing(NARROWER) == []


def _save(client: TestClient, limits: dict[str, object]) -> None:
    revision = client.get(SETTINGS).json()["revision"]
    response = client.patch(
        SETTINGS, json={"revision": revision, "changes": {"template_positions": limits}}
    )
    assert response.status_code == 200, response.text


def _queued(app) -> list[tuple[str, str]]:
    return [
        (job.template, job.kind)
        for job in app.state.preparations.list_jobs()
        if job.phase == "queued"
    ]


@pytest.mark.parametrize(("limits", "queued"), [(WIDER, [("tee", "coverage")]), (NARROWER, [])])
def test_saving_limits_queues_coverage_only_when_they_widen(
    workspace: Workspace, limits: dict[str, object], queued: list[tuple[str, str]]
):
    app = create_app(workspace, preparation_runtime=PreparationRuntime())

    _save(TestClient(app), limits)

    assert _queued(app) == queued


@pytest.mark.parametrize(("positions", "coverage"), [("kept", 1), ("removed", 0)])
def test_recalibrating_a_positioned_template_queues_coverage_for_its_new_box(
    workspace: Workspace, positions: str, coverage: int
):
    """The moved box's padded quad leaves the evidence; only a template some
    listing positions gets inference for it (spec *Recalibration*)."""
    if positions == "removed":
        edit_listing(workspace.root, template_positions={})
    app = create_app(workspace, preparation_runtime=PreparationRuntime())
    client = TestClient(app)
    loaded = client.get("/api/templates/tee/config")
    config = loaded.json()
    config["bounding_box"] = [
        {"x": point["x"] + 14, "y": point["y"] + 14} for point in config["bounding_box"]
    ]

    saved = client.put(
        "/api/templates/tee/config",
        headers={"If-Match": loaded.headers["etag"]},
        json={"request_id": "move-tee", "config": config},
    )

    assert saved.status_code == 200, saved.text
    assert [kind for _, kind in _queued(app)].count("coverage") == coverage


def test_impact_refuses_cleanly_when_settings_do_not_load(workspace: Workspace):
    """The unreadable-settings refusal PR 2 gives listings (naming the file and
    the key), not a server error."""
    workspace.settings_file().write_bytes(b"template_positions:\n  rotation: lots\n")
    client = TestClient(create_app(workspace, preparation_runtime=PreparationRuntime()))

    refused = client.post(IMPACT, json={"limits": WIDER})

    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["kind"] == "invalid"
    assert "settings.yaml" in body["message"]
    assert "template_positions.rotation" in body["message"]

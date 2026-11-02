"""Saving a Marigold listing position through ``PATCH /api/listings/{name}``
queues what it needs in the background (spec *Rendering → Marigold (option
B)*, *When fits run*): coverage inference when the template's evidence does not
reach the padded quad, else the fit itself, through the scene warmer."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.server.api.app import create_app

from tests.support.builders import FIXTURE_LISTING, edit_listing
from tests.support.marigold import (
    PreparationRuntime,
    listing_with_prepared_marigold,
    prepare_template,
    small_print,
)

URL = f"/api/listings/{FIXTURE_LISTING}"


def _position(workspace, template: str) -> dict[str, object]:
    box = compose(
        workspace.load_template_config(template).bounding_box, Pose(scale=0.95, rotation=5)
    )
    return {template: {"bounding_box": [point.model_dump() for point in box]}}


def test_a_position_its_evidence_misses_queues_coverage_inference(workspace_root: Path):
    workspace = small_print(workspace_root)
    prepare_template(workspace, "tee")
    edit_listing(workspace_root, media=[{"template": "tee"}])
    app = create_app(workspace, preparation_runtime=PreparationRuntime())

    response = TestClient(app).patch(URL, json={"template_positions": _position(workspace, "tee")})

    assert response.status_code == 200, response.text
    jobs = app.state.preparations.list_jobs(template="tee")
    assert [job.kind for job in jobs if job.phase == "queued"] == ["coverage"]


def test_a_covered_position_is_fitted_in_the_background(workspace_root: Path):
    workspace = listing_with_prepared_marigold(workspace_root)
    app = create_app(workspace, preparation_runtime=PreparationRuntime())
    with TestClient(app) as client:
        response = client.patch(URL, json={"template_positions": _position(workspace, "shirt")})
        assert response.status_code == 200, response.text
        assert app.state.scene_warmer.wait_idle(timeout=30)

    assert len(workspace.position_fits()) == 1
    assert [job.kind for job in app.state.preparations.list_jobs()] == ["prepare"]

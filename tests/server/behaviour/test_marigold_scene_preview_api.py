"""``GET /api/listings/{name}/scene-preview`` for a Marigold template: the
prepared scene the render stage writes, or a refusal while maps are missing --
never Photo warp, and never a server error."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.engine.stages.render import RenderStage, scene_hash
from etsy_listings.server.api.app import create_app

from tests.support.builders import FIXTURE_LISTING, a_context
from tests.support.marigold import listing_with_marigold

URL = f"/api/listings/{FIXTURE_LISTING}/scene-preview"


def test_a_prepared_template_previews_the_scene_the_render_stage_writes(
    workspace_root: Path,
) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    stage = RenderStage()
    desired = stage.desired(a_context(workspace_root), FIXTURE_LISTING, None)

    response = TestClient(create_app(workspace)).get(URL, params={"template": "shirt"})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["X-Render-Identity"] == scene_hash(desired, desired.works[0])


def test_an_unprepared_template_refuses_with_the_preparation_message(
    workspace_root: Path,
) -> None:
    workspace, _ = listing_with_marigold(workspace_root)

    response = TestClient(create_app(workspace)).get(URL, params={"template": "shirt"})

    assert response.status_code == 409
    assert "Prepare the template first" in response.json()["detail"]

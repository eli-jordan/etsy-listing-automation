"""``GET /api/listings/{name}/scene-preview`` for a Marigold template: the
prepared scene the render stage writes, or a refusal while maps are missing --
never Photo warp, and never a server error."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from etsy_listings.core.engine.stages.render import RenderStage, scene_hash
from etsy_listings.core.workspace.template_state import template_state
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


def _position(workspace) -> dict[str, object]:
    from etsy_listings.core.render.positions import Pose, compose

    box = compose(
        template_state(workspace, "shirt").require().bounding_box,
        Pose(scale=0.9, offset_x=0.05, rotation=8),
    )
    return {"shirt": {"bounding_box": [point.model_dump() for point in box]}}


def test_a_saved_position_previews_its_fit_as_the_render_stage_renders_it(
    workspace_root: Path,
) -> None:
    """The fit is not stored when the preview is asked: the route fits it
    and waits, then shows the scene ``plan`` hashes (option B)."""
    from tests.support.builders import edit_listing
    from tests.support.marigold import listing_with_prepared_marigold

    workspace = listing_with_prepared_marigold(workspace_root)
    unpositioned = TestClient(create_app(workspace)).get(URL, params={"template": "shirt"})
    edit_listing(workspace_root, template_positions=_position(workspace))

    response = TestClient(create_app(workspace)).get(URL, params={"template": "shirt"})

    assert response.status_code == 200, response.text
    assert len(workspace.position_fits()) == 1
    desired = RenderStage().desired(a_context(workspace_root), FIXTURE_LISTING, None)
    identity = response.headers["X-Render-Identity"]
    assert identity == scene_hash(desired, desired.works[0])
    assert identity != unpositioned.headers["X-Render-Identity"]
    again = TestClient(create_app(workspace)).get(URL, params={"template": "shirt"})
    assert again.content == response.content


def test_a_position_its_evidence_misses_refuses_like_unprepared_maps(
    workspace_root: Path,
) -> None:
    from tests.support.builders import edit_listing

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    edit_listing(workspace_root, template_positions=_position(workspace))

    response = TestClient(create_app(workspace)).get(URL, params={"template": "shirt"})

    assert response.status_code == 409
    assert "cover listing positions" in response.json()["detail"]

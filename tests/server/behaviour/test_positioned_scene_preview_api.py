"""The Listing Images preview shows the listing's *saved* template position
(interactions *Adjusting*; spec *Rendering → Photo warp*): the scene-preview
route and the save-time warm-up compose the scene the render stage writes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.application.scene_warming import SceneWarmer
from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.plan import build_plan
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock
from tests.support.scenes import expected_scene

DESIGN = "designs/take-a-hike.png"
URL = f"/api/listings/{LISTING}/scene-preview"


@pytest.fixture
def client(workspace_root: Path) -> Iterator[TestClient]:
    with TestClient(create_app(Workspace.discover(root_override=workspace_root))) as client:
        yield client


def _positions(root: Path) -> tuple[dict[str, object], object, object]:
    workspace = Workspace.discover(root_override=root)
    flat = compose(
        workspace.load_template_config("flat-lay-01").bounding_box,
        Pose(scale=0.9, offset_x=-0.06, rotation=10),
    )
    chart = workspace.load_template_config("colour-chart-01")
    placement = compose(chart.placements[1].bounding_box, Pose(scale=1.05, offset_y=0.04))
    positions = {
        "flat-lay-01": {"bounding_box": [p.model_dump() for p in flat]},
        "colour-chart-01": {
            "placements": {
                "fixture-placement-2": {"bounding_box": [p.model_dump() for p in placement]}
            }
        },
    }
    return positions, flat, placement


def _save(client: TestClient, positions: dict[str, object]) -> None:
    response = client.patch(
        f"/api/listings/{LISTING}",
        json={
            "media": [
                {"template": "flat-lay-01", "colour": "moss"},
                {"template": "colour-chart-01"},
            ],
            "template_positions": positions,
        },
    )
    assert response.status_code == 200, response.text


def _preview(client: TestClient, **params: str) -> bytes:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.content


def test_the_preview_shows_the_saved_position_as_the_render_stage_writes_it(
    client: TestClient, workspace_root: Path
) -> None:
    positions, flat, placement = _positions(workspace_root)
    _save(client, positions)

    moss = _preview(client, template="flat-lay-01", colour="moss")
    chart = _preview(client, template="colour-chart-01")

    files = {"black": DESIGN, "moss": DESIGN}
    assert moss == expected_scene(workspace_root, "flat-lay-01", "moss", files, boxes={None: flat})
    assert chart == expected_scene(
        workspace_root, "colour-chart-01", None, files, boxes={"fixture-placement-2": placement}
    )
    ctx = a_context(workspace_root)
    execute(ctx, build_plan(ctx, LISTING, a_lock(), STAGES), a_lock())
    assert ctx.workspace.render_file(LISTING, "flat-lay-01", "moss").read_bytes() == moss
    assert ctx.workspace.render_file(LISTING, "colour-chart-01", None).read_bytes() == chart


def test_saving_a_position_warms_the_positioned_scene(
    client: TestClient, workspace_root: Path
) -> None:
    positions, flat, placement = _positions(workspace_root)
    _save(client, positions)

    warmer: SceneWarmer = client.app.state.scene_warmer  # type: ignore[attr-defined]  # -- untyped app
    assert warmer.wait_idle(timeout=30)
    cache = Workspace.discover(root_override=workspace_root).scene_cache_dir()
    cached = {path.read_bytes() for path in cache.rglob("*") if path.is_file()}
    files = {"black": DESIGN, "moss": DESIGN}
    assert cached == {
        expected_scene(workspace_root, "flat-lay-01", "moss", files, boxes={None: flat}),
        expected_scene(
            workspace_root, "colour-chart-01", None, files, boxes={"fixture-placement-2": placement}
        ),
    }

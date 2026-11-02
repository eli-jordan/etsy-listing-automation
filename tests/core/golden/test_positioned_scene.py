"""Golden composites of Photo warp scenes rendered at a listing's position
(template positions plan PR 3): the render stage's own output for a moved,
resized and tilted colour-matrix box and one moved chart placement."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.plan import build_plan
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.render.positions import Pose, compose

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, edit_listing

GOLDENS = Path(__file__).parent / "goldens"


@pytest.fixture
def rendered(workspace_root: Path):
    workspace = a_context(workspace_root).workspace
    flat = workspace.load_template_config("flat-lay-01")
    chart = workspace.load_template_config("colour-chart-01")
    placement = next(p for p in chart.placements if p.id == "fixture-placement-1")

    def corners(box):
        return [point.model_dump() for point in box]

    edit_listing(
        workspace_root,
        media=[{"template": "flat-lay-01", "colour": "black"}, {"template": "colour-chart-01"}],
        template_positions={
            "flat-lay-01": {
                "bounding_box": corners(
                    compose(flat.bounding_box, Pose(scale=0.85, offset_x=0.08, rotation=12))
                )
            },
            "colour-chart-01": {
                "placements": {
                    "fixture-placement-1": {
                        "bounding_box": corners(
                            compose(
                                placement.bounding_box,
                                Pose(scale=1.1, offset_y=-0.1, rotation=-15),
                            )
                        )
                    }
                }
            },
        },
    )
    ctx = a_context(workspace_root)
    execute(ctx, build_plan(ctx, LISTING, a_lock(), STAGES), a_lock())
    return workspace


@pytest.mark.parametrize(
    ("template", "colour", "golden"),
    [
        ("flat-lay-01", "black", "positioned-flat-lay-black.png"),
        ("colour-chart-01", None, "positioned-colour-chart.png"),
    ],
)
def test_positioned_scene_golden(
    rendered, template: str, colour: str | None, golden: str, assert_matches_golden
) -> None:
    with Image.open(rendered.render_file(LISTING, template, colour)) as image:
        assert_matches_golden(image.convert("RGB"), GOLDENS / golden)

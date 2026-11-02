"""A Marigold scene rendered at a listing's position is a direct fit of its
posed quad (spec *Rendering → Marigold (option B: a fit per position)*): the
render stage's file equals the scene composed from maps fitted to that quad
from the template's own evidence, with the controlled predictor's evidence."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from etsy_listings.core.engine import build_plan, execute
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.preparation.evidence_reader import EvidenceReader
from etsy_listings.core.preparation.numerics import Placement, prepare
from etsy_listings.core.render import MaterialLayer, load_design, render_marigold_scene
from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.calibration import CalibrationStore

from tests.support.builders import FIXTURE_LISTING, a_context, a_lock, edit_listing
from tests.support.marigold import listing_with_prepared_marigold

GOLDEN = Path(__file__).parent / "goldens" / "positioned-marigold.png"
POSE = Pose(scale=0.9, offset_x=0.05, offset_y=-0.04, rotation=10)


def _scene(workspace, quad, design):
    """The scene composed from maps fitted directly to ``quad``."""
    base = np.array(Image.open(workspace.template_main_photo("shirt")).convert("RGB"))
    mask = np.array(Image.open(BytesIO(CalibrationStore(workspace).mask("shirt").edited)))
    reader = EvidenceReader(workspace)
    evidence = reader.load(reader.current("shirt")[0], reader.pointer("shirt").inputs)
    maps = prepare(base, Placement(quad, mask.astype(np.float32) / 255), evidence).maps
    appearance = workspace.load_template_config("shirt").renderer.config.appearance
    layers = [MaterialLayer(load_design(design), maps)]
    return render_marigold_scene(base, layers, appearance=appearance)


def test_a_positioned_marigold_scene_is_a_direct_fit_of_its_posed_quad(
    workspace_root, assert_matches_golden
):
    workspace = listing_with_prepared_marigold(workspace_root)
    template = workspace.load_template_config("shirt")
    posed = compose(template.bounding_box, POSE)
    edit_listing(
        workspace_root,
        template_positions={"shirt": {"bounding_box": [p.model_dump() for p in posed]}},
    )
    ctx = a_context(workspace_root)
    planned = build_plan(ctx, FIXTURE_LISTING, a_lock(), (RenderStage(),))
    assert planned.plan.stage_plans[0].blocked is None
    design = RenderStage().desired(ctx, FIXTURE_LISTING, None).works[0].layers[0].design
    execute(ctx, planned, a_lock())

    with Image.open(workspace.render_file(FIXTURE_LISTING, "shirt", None)) as file:
        rendered = file.convert("RGB")
    quad = np.array([(p.x, p.y) for p in posed], np.float32)
    assert np.array_equal(np.asarray(rendered), np.asarray(_scene(workspace, quad, design)))
    own = np.array([(p.x, p.y) for p in template.bounding_box], np.float32)
    assert not np.array_equal(np.asarray(rendered), np.asarray(_scene(workspace, own, design)))
    assert_matches_golden(rendered, GOLDEN)

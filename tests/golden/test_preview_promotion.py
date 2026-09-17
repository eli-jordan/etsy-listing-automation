"""A promoted preview is byte-identical to a direct render of the same scene
(A32, decision 6). Two independent copies of the fixture workspace: one plans,
previews, then applies (promoting every preview); the other applies directly,
with no preview ever involved. `render` passes are pure and OpenCV/Pillow are
pinned exactly (A7), so the two runs must produce the same bytes -- this is
what actually verifies that claim, rather than merely asserting it in a
docstring."""

from __future__ import annotations

import shutil
from pathlib import Path

from etsy_listings.engine.apply import execute
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.render import RenderStage

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock

FIXTURE_WORKSPACE = Path(__file__).parent.parent / "fixtures" / "workspace"


def _fresh_workspace(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copytree(FIXTURE_WORKSPACE, dest)
    return dest


def test_promoted_preview_matches_a_fresh_render_byte_for_byte(tmp_path: Path) -> None:
    previewed_root = _fresh_workspace(tmp_path, "previewed")
    fresh_root = _fresh_workspace(tmp_path, "fresh")

    ctx = a_context(previewed_root)
    planned = build_plan(ctx, LISTING, a_lock(), STAGES)
    render_state = next(s for s in planned.states if s.stage.name == "render")
    stage = render_state.stage
    assert isinstance(stage, RenderStage)

    rendered_previews = stage.preview(ctx, render_state.desired, render_state.live)
    assert rendered_previews  # sanity: this listing has scenes that needed one

    execute(ctx, planned, a_lock())

    fresh_ctx = a_context(fresh_root)
    fresh_planned = build_plan(fresh_ctx, LISTING, a_lock(), STAGES)
    execute(fresh_ctx, fresh_planned, a_lock())

    assert render_state.desired.works, "sanity: the fixture listing has scenes to compare"
    for work in render_state.desired.works:
        promoted = ctx.workspace.render_file(LISTING, work.template, work.colour).read_bytes()
        fresh = fresh_ctx.workspace.render_file(LISTING, work.template, work.colour).read_bytes()
        assert promoted == fresh, f"{work.key}: promoted preview differs from a fresh render"

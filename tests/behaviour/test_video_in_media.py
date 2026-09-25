"""A video in `media:` is invisible to every stage that exists today (PRD 71).

`media:` is the gallery, so a video sits between images -- at position 2,
where Etsy features it. Until `etsy_videos` exists, nothing may read that
entry as an image: `render` renders nothing for it, Printify and the listing
stages never see it, and `etsy_media` ranks the images around it exactly as
if it were not there. The test applies a listing without a video, adds one,
and asks `plan` about every stage.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from etsy_listings.engine.run import apply_listings, plan_listings

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing
from tests.support.pipeline import a_deployable_context, real_stages

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
THUMB = {"template": "flat-lay-01", "colour": "black"}
SECOND = {"template": "flat-lay-01", "colour": "moss"}
CLIP = "common-media/size-guide.mp4"


def test_adding_a_featured_video_leaves_every_stage_with_nothing_to_do(
    workspace_root: Path,
) -> None:
    ctx = a_deployable_context(workspace_root)
    edit_listing(workspace_root, media=[THUMB, SECOND])
    applied = apply_listings(ctx, [LISTING], real_stages())
    assert applied.outcomes[0].ok, applied.outcomes[0].error

    (workspace_root / "common-media").mkdir()
    shutil.copy(VIDEOS / "valid-3s-512.mp4", workspace_root / CLIP)
    edit_listing(workspace_root, media=[THUMB, CLIP, SECOND])

    planned = plan_listings(ctx, [LISTING], real_stages()).outcomes[0].planned
    assert planned is not None
    for stage_plan in planned.plan.stage_plans:
        assert stage_plan.blocked is None, (stage_plan.stage, stage_plan.blocked)
        assert not stage_plan.will_run, (stage_plan.stage, stage_plan.reason)
        assert stage_plan.changes == (), stage_plan.stage

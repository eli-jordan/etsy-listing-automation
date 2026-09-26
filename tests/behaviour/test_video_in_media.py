"""A video in `media:` is `etsy_videos`' business alone (PRD 71).

`media:` is the gallery, so a video sits between images -- at position 2,
where Etsy features it. Nothing else may read that entry as an image:
`render` renders nothing for it, Printify and the listing stages never see
it, and `etsy_media` ranks the images around it exactly as if it were not
there. The test applies a listing without a video, adds one, and asks `plan`
about every stage.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.engine.run import apply_listings, plan_listings

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing
from tests.support.pipeline import ETSY_LISTING_ID, a_deployable_context, real_stages

VIDEOS = Path(__file__).parent.parent / "fixtures" / "video"
THUMB = {"template": "flat-lay-01", "colour": "black"}
SECOND = {"template": "flat-lay-01", "colour": "moss"}
CLIP = "common-media/size-guide.mp4"


def test_adding_a_featured_video_is_work_for_the_video_stage_alone(
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
    assert [sp.stage for sp in planned.plan.stage_plans if sp.will_run] == ["etsy_videos"]
    for stage_plan in planned.plan.stage_plans:
        assert stage_plan.blocked is None, (stage_plan.stage, stage_plan.blocked)
        if stage_plan.stage != "etsy_videos":
            assert stage_plan.changes == (), stage_plan.stage


def test_the_whole_pipeline_places_the_video_at_position_two(workspace_root: Path) -> None:
    ctx = a_deployable_context(workspace_root)
    (workspace_root / "common-media").mkdir()
    shutil.copy(VIDEOS / "valid-3s-512.mp4", workspace_root / CLIP)
    edit_listing(workspace_root, media=[THUMB, CLIP, SECOND])

    applied = apply_listings(ctx, [LISTING], real_stages())

    assert applied.outcomes[0].ok, applied.outcomes[0].error
    etsy = ctx.require_etsy()
    assert isinstance(etsy, FakeEtsyListingClient)
    assert [slot.kind for slot in etsy.gallery(ETSY_LISTING_ID)] == ["image", "video", "image"]

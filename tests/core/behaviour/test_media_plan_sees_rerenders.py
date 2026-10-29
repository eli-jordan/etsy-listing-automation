"""`etsy_media`'s plan when the `render` stage before it will re-render a scene.

The media stage hashes the file it will upload. At plan time a scene whose
photo, template or artwork changed still has its *previous* render on disk,
so hashing that file reported "no changes", `apply` skipped the stage, and
the re-rendered mockup never reached Etsy. These run the real render stage
ahead of the media stage, the way `STAGES` orders them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageOps

from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.core.engine.apply import execute
from etsy_listings.core.engine.change import MediaChange, StagePlan
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.plan import PlannedRun, build_plan
from etsy_listings.core.engine.run import preview_listing
from etsy_listings.core.engine.stages.etsy_media import EtsyMediaStage
from etsy_listings.core.engine.stages.render import RenderStage

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, set_etsy_shop_id

ETSY_LISTING_ID = 4572550919
SHOP_ID = 12345678
TEMPLATE = "flat-lay-01"
BLACK = f"{TEMPLATE}:black"
STAGES = [RenderStage(), EtsyMediaStage()]


@pytest.fixture(autouse=True)
def _etsy_shop(workspace_root: Path) -> None:
    set_etsy_shop_id(workspace_root, SHOP_ID)


@pytest.fixture
def ctx(workspace_root: Path) -> RunContext:
    etsy = FakeEtsyListingClient()
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID)
    return a_context(workspace_root, etsy=etsy)


def _etsy(ctx: RunContext) -> FakeEtsyListingClient:
    assert isinstance(ctx.etsy, FakeEtsyListingClient)
    return ctx.etsy


def _plan(ctx: RunContext, lock: Lockfile) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, STAGES)


def _media(planned: PlannedRun) -> StagePlan:
    return next(sp for sp in planned.plan.stage_plans if sp.stage == "etsy_media")


def _deployed(ctx: RunContext) -> Lockfile:
    lock = a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})
    return execute(ctx, _plan(ctx, lock), lock)


def _replace_black_photo(root: Path) -> None:
    """New pixels, not just new bytes: a re-render of the same pixels is
    byte-identical, which is the no-change case."""
    photo = root / "mockup-templates" / TEMPLATE / "black.png"
    with Image.open(photo) as image:
        replaced = ImageOps.invert(image.convert("RGB"))
    replaced.save(photo)


def test_a_replaced_photo_makes_the_media_stage_run(ctx: RunContext, workspace_root: Path) -> None:
    lock = _deployed(ctx)
    _replace_black_photo(workspace_root)

    media = _media(_plan(ctx, lock))

    assert media.will_run
    assert media.changes == (MediaChange(rank=1, before=BLACK, after=BLACK),)


def test_one_apply_re_renders_and_uploads_only_the_changed_image(
    ctx: RunContext, workspace_root: Path
) -> None:
    lock = _deployed(ctx)
    uploads_before = len(_etsy(ctx).uploads)
    _replace_black_photo(workspace_root)

    execute(ctx, _plan(ctx, lock), lock)

    assert len(_etsy(ctx).uploads) == uploads_before + 1


def test_a_plan_after_previews_still_reports_the_changed_image(
    ctx: RunContext, workspace_root: Path
) -> None:
    lock = _deployed(ctx)
    _replace_black_photo(workspace_root)
    preview_listing(ctx, _plan(ctx, lock))

    media = _media(_plan(ctx, lock))

    assert media.will_run
    assert media.changes == (MediaChange(rank=1, before=BLACK, after=BLACK),)
    assert media.actions[0].missing_outputs == ()


def test_a_re_render_with_identical_pixels_changes_nothing_once_previewed(
    ctx: RunContext, workspace_root: Path
) -> None:
    """A comment in `template.yaml` re-renders every scene, but the previews
    prove the pixels match what Etsy already has."""
    lock = _deployed(ctx)
    config = workspace_root / "mockup-templates" / TEMPLATE / "template.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")
    preview_listing(ctx, _plan(ctx, lock))

    media = _media(_plan(ctx, lock))

    assert not media.will_run
    assert media.changes == ()

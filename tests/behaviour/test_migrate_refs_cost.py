"""PRD 73's cost claim, pinned: migrating a workspace's refs re-uploads its
shared images once, and nothing else.

A workspace is applied end to end against in-memory clients, then put back
the way the old code would have left it -- `listing.yaml` in the
listing-relative `../../` form, and `etsy_media`'s manifest keyed by those
same refs. `scripts/migrate_workspace_refs.py` rewrites it, and `plan` must
then say that `render`, `printify_product` and `publish` have nothing to do
(the render hash and Printify's upload ids are keyed by a design's bytes,
never by the text naming it) while `etsy_media` wants exactly the renamed
shared image.

The reconstruction is only honest if no other applied document names a ref,
so that is asserted too: if one ever did, the old code's lockfile would have
differed there as well and this test could not stand in for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from scripts.migrate_workspace_refs import main as migrate

from etsy_listings.engine.change import MediaChange
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.run import apply_listings, plan_listings

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import edit_listing, listing_file
from tests.support.pipeline import DESIGN, PLAN, a_deployable_context, real_stages

SHARED = "common-media/size-guide.png"


@pytest.fixture
def ctx(workspace_root: Path) -> RunContext:
    ctx = a_deployable_context(workspace_root)
    (workspace_root / "common-media").mkdir()
    Image.new("RGB", (64, 64), (200, 200, 200)).save(workspace_root / SHARED)
    edit_listing(workspace_root, media=[{"template": "flat-lay-01", "colour": "black"}, SHARED])
    return ctx


def _as_the_old_code_left_it(root: Path) -> None:
    listing = listing_file(root)
    text = listing.read_text(encoding="utf-8")
    for ref in (DESIGN, PLAN, SHARED):
        text = text.replace(ref, f"../../{ref}")
    listing.write_text(text, encoding="utf-8")

    lock_path = listing.parent / "state.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for entry in lock["applied"]["etsy_media"]["manifest"]:
        if entry["ref"] == SHARED:
            entry["ref"] = f"../../{SHARED}"
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")


def test_migrating_re_uploads_the_shared_image_and_changes_nothing_else(
    ctx: RunContext, workspace_root: Path
) -> None:
    applied = apply_listings(ctx, [LISTING], real_stages())
    assert applied.outcomes[0].ok, applied.outcomes[0].error
    lock = json.loads((listing_file(workspace_root).parent / "state.lock.json").read_text())
    for stage in ("render", "printify_product", "publish"):
        assert stage in lock["applied"]
        for ref in (DESIGN, PLAN, SHARED):
            assert ref not in json.dumps(lock["applied"][stage]), (stage, ref)

    _as_the_old_code_left_it(workspace_root)
    assert migrate([str(workspace_root), "--write"]) == 0

    planned = plan_listings(ctx, [LISTING], real_stages()).outcomes[0].planned
    assert planned is not None
    by_stage = {sp.stage: sp for sp in planned.plan.stage_plans}
    for stage in ("render", "printify_product", "publish", "etsy_listing"):
        stage_plan = by_stage[stage]
        assert not stage_plan.will_run, (stage, stage_plan.reason)
        assert stage_plan.blocked is None, (stage, stage_plan.blocked)
    media = by_stage["etsy_media"]
    assert media.will_run
    changes = [c for c in media.changes if isinstance(c, MediaChange)]
    assert changes == [MediaChange(rank=2, before=f"../../{SHARED}", after=SHARED)]

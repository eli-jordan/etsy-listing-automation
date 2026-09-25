"""PRD 72's cost claim, pinned: migrating a workspace's refs re-uploads its
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

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.models import ReturnPolicy, ShippingProfile
from etsy_listings.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ProductExternal,
    Shop,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.engine.change import MediaChange
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.run import apply_listings, plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.publish import PublishStage

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    edit_listing,
    listing_file,
    set_copy,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
    set_shop_id,
    write_design,
)

SHOP_ID = 28819281
ETSY_SHOP_ID = 12345678
ETSY_LISTING_ID = 4572550919
PRINT_AREA = (4500, 5400)
SHARED = "common-media/size-guide.png"
PLAN = "pricing-plans/launch.yaml"
DESIGN = "designs/take-a-hike.png"
COLOURS = ["Black", "Blue Jean", "Ivory", "Moss"]
SIZES = ["S", "M", "L", "XL", "XXL", "XXXL"]


def _catalog() -> FakeCatalogClient:
    placeholder = PrintAreaPlaceholder(position="front", width=PRINT_AREA[0], height=PRINT_AREA[1])
    variants = VariantSet(
        variants=tuple(
            Variant(
                id=1000 + c * 10 + s,
                title=f"{colour} / {size}",
                options=VariantOptions(color=colour, size=size),
                placeholders=(placeholder,),
            )
            for c, colour in enumerate(COLOURS)
            for s, size in enumerate(SIZES)
        )
    )
    return FakeCatalogClient(
        blueprints=[
            Blueprint(
                id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
            )
        ],
        providers_by_blueprint={706: [PrintProvider(id=29, title="Monster Digital")]},
        variants_by_key={(706, 29): variants},
    )


@pytest.fixture
def ctx(workspace_root: Path) -> RunContext:
    root = workspace_root
    set_shop_id(root, SHOP_ID)
    set_etsy_shop_id(root, ETSY_SHOP_ID)
    set_etsy_listing_defaults(root, shipping_profile="NOK standard tee")
    set_copy(root, title="Take A Hike Tee", description="A retro sunset.")
    write_design(root, PRINT_AREA)
    (root / "common-media").mkdir()
    Image.new("RGB", (64, 64), (200, 200, 200)).save(root / SHARED)
    (root / "pricing-plans").mkdir()
    (root / PLAN).write_text(
        "garment_profile: comfort-colors-1717\nprices:\n"
        + "".join(f"  {size}: 349 NOK\n" for size in SIZES),
        encoding="utf-8",
    )
    edit_listing(
        root,
        design=DESIGN,
        pricing_plan=PLAN,
        prices={},
        media=[{"template": "flat-lay-01", "colour": "black"}, SHARED],
    )

    printify = FakePrintifyClient([Shop(id=SHOP_ID, title="My new store")])
    printify.publish_external["fake-product-1"] = ProductExternal(
        id=str(ETSY_LISTING_ID), handle="https://www.etsy.com/listing/4572550919/x"
    )
    etsy = FakeEtsyListingClient(
        shipping_profiles=[ShippingProfile(shipping_profile_id=1, title="NOK standard tee")],
        policies=[
            ReturnPolicy(
                return_policy_id=99,
                accepts_returns=True,
                accepts_exchanges=True,
                return_deadline=30,
            )
        ],
    )
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID, state="draft")
    return a_context(root, catalog=_catalog(), printify=printify, etsy=etsy)


def _stages() -> list[object]:
    """The real pipeline, with `publish`'s poll unable to wait."""
    return [PublishStage(sleep=lambda seconds: None) if s.name == "publish" else s for s in STAGES]


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
    applied = apply_listings(ctx, [LISTING], _stages())
    assert applied.outcomes[0].ok, applied.outcomes[0].error
    lock = json.loads((listing_file(workspace_root).parent / "state.lock.json").read_text())
    for stage in ("render", "printify_product", "publish"):
        assert stage in lock["applied"]
        for ref in (DESIGN, PLAN, SHARED):
            assert ref not in json.dumps(lock["applied"][stage]), (stage, ref)

    _as_the_old_code_left_it(workspace_root)
    assert migrate([str(workspace_root), "--write"]) == 0

    planned = plan_listings(ctx, [LISTING], _stages()).outcomes[0].planned
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

"""The `etsy_media` stage, against `FakeEtsyListingClient` (A4).

Render files are written directly at the path `workspace.render_file()`
computes rather than produced by running `RenderStage` -- this stage's own
job starts once bytes exist on disk, and driving the real renderer here
would just be slow, duplicate coverage of `test_render_outputs.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.clients.etsy.models import (
    Inventory,
    InventoryProduct,
    InventoryPropertyValue,
)
from etsy_listings.engine.apply import execute
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, build_plan
from etsy_listings.engine.stages.etsy_media import (
    EtsyMediaStage,
    EtsyMediaWithoutListingError,
    MediaNotRenderedError,
)

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock, edit_listing, set_etsy_shop_id

ETSY_LISTING_ID = 4572550919
SHOP_ID = 12345678
STAGE = EtsyMediaStage()
COLOURS = ["black", "blue-jean", "ivory", "moss"]
TEMPLATE = "flat-lay-01"


@pytest.fixture(autouse=True)
def _etsy_shop(workspace_root: Path) -> None:
    set_etsy_shop_id(workspace_root, SHOP_ID)


@pytest.fixture
def etsy() -> FakeEtsyListingClient:
    client = FakeEtsyListingClient()
    client.seed_listing(ETSY_LISTING_ID, shop_id=SHOP_ID)
    return client


def _write_renders(
    root: Path, *, colours: list[str] = COLOURS, content: bytes = b"png-bytes"
) -> None:
    workspace_ctx = a_context(root)
    for colour in colours:
        path = workspace_ctx.workspace.render_file(LISTING, TEMPLATE, colour)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content + colour.encode())


def _ctx(root: Path, etsy: FakeEtsyListingClient) -> RunContext:
    return a_context(root, etsy=etsy)


def _plan(ctx: RunContext, lock: Lockfile) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, [STAGE])


def _stage_plan(ctx: RunContext, lock: Lockfile):
    return _plan(ctx, lock).plan.stage_plans[0]


def _lock_with_listing_id(**remote: object) -> Lockfile:
    return a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID, **remote})


def _apply(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, _plan(ctx, lock), lock)


# ------------------------------------------------------------------ pending


def test_a_render_not_yet_on_disk_is_reported_pending(workspace_root: Path, etsy) -> None:
    stage_plan = _stage_plan(_ctx(workspace_root, etsy), a_lock())

    assert stage_plan.will_run
    assert "pending render" in (stage_plan.reason or "")


def test_apply_refuses_to_upload_a_pending_render(workspace_root: Path, etsy) -> None:
    ctx = _ctx(workspace_root, etsy)

    with pytest.raises(MediaNotRenderedError):
        _apply(ctx, _lock_with_listing_id())


# -------------------------------------------------------------- first upload


def test_the_first_plan_reports_every_image(workspace_root: Path, etsy) -> None:
    _write_renders(workspace_root)

    stage_plan = _stage_plan(_ctx(workspace_root, etsy), a_lock())

    assert stage_plan.will_run
    assert "4 images" in (stage_plan.reason or "")


def test_apply_uploads_every_entry_and_sets_the_order(workspace_root: Path, etsy) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)

    result = _apply(ctx, _lock_with_listing_id())

    assert len(etsy.updated[-1]["image_ids"]) == 4
    manifest = result.applied["etsy_media"]["manifest"]
    assert [entry["ref"] for entry in manifest] == [f"{TEMPLATE}:{c}" for c in COLOURS]
    assert result.remote["etsy_image_ids"]
    assert len(result.remote["etsy_image_ids"]) == 4


def test_apply_without_a_listing_id_fails_loudly(workspace_root: Path, etsy) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)

    with pytest.raises(EtsyMediaWithoutListingError):
        _apply(ctx, a_lock())


# --------------------------------------------------------------------- no-op


def test_a_second_apply_with_nothing_changed_uploads_nothing(workspace_root: Path, etsy) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    uploads_before = len(etsy.uploads)

    stage_plan = _stage_plan(ctx, lock)
    assert stage_plan.will_run is False

    lock = _apply(ctx, lock)
    assert len(etsy.uploads) == uploads_before


# ------------------------------------------------------------- reorder/detach


def test_reordering_media_sends_a_new_image_ids_order_without_reuploading(
    workspace_root: Path, etsy
) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    uploads_before = len(etsy.uploads)
    first_image_ids = dict(lock.remote["etsy_image_ids"])

    edit_listing(
        workspace_root,
        media=[
            {"template": TEMPLATE, "colour": "moss"},
            {"template": TEMPLATE, "colour": "black"},
            {"template": TEMPLATE, "colour": "blue-jean"},
            {"template": TEMPLATE, "colour": "ivory"},
        ],
    )

    lock = _apply(ctx, lock)

    assert len(etsy.uploads) == uploads_before, "no bytes should be re-sent for a pure reorder"
    new_order = etsy.updated[-1]["image_ids"]
    assert new_order[0] == first_image_ids[f"{TEMPLATE}:moss"]
    assert new_order[1] == first_image_ids[f"{TEMPLATE}:black"]


def test_dropping_a_media_entry_detaches_it_from_image_ids(workspace_root: Path, etsy) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())

    edit_listing(
        workspace_root,
        media=[
            {"template": TEMPLATE, "colour": "black"},
            {"template": TEMPLATE, "colour": "blue-jean"},
            {"template": TEMPLATE, "colour": "ivory"},
        ],
    )

    lock = _apply(ctx, lock)

    assert len(etsy.updated[-1]["image_ids"]) == 3
    live = etsy.get_listing(ETSY_LISTING_ID, include_images=True)
    assert live is not None
    assert len(live.images) == 3


def test_changed_bytes_trigger_a_reupload_of_only_that_entry(workspace_root: Path, etsy) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    uploads_before = len(etsy.uploads)

    _write_renders(workspace_root, colours=["black"], content=b"changed-bytes")

    lock = _apply(ctx, lock)

    assert len(etsy.uploads) == uploads_before + 1


# --------------------------------------------------------------------- drift


def test_an_image_deleted_outside_the_tool_is_drift_and_gets_reuploaded(
    workspace_root: Path, etsy
) -> None:
    _write_renders(workspace_root)
    ctx = _ctx(workspace_root, etsy)
    lock = _apply(ctx, _lock_with_listing_id())
    original_ids = dict(lock.remote["etsy_image_ids"])

    # Simulate Printify (or a human) replacing the image behind our back.
    etsy.upload_listing_image(
        SHOP_ID,
        ETSY_LISTING_ID,
        file_name="replacement.png",
        contents=b"someone-elses-upload",
        rank=1,
        overwrite=True,
        listing_image_id=original_ids[f"{TEMPLATE}:black"],
    )

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.will_run
    assert stage_plan.drift


# -------------------------------------------------------------- variation images


def _seed_inventory(etsy: FakeEtsyListingClient) -> None:
    products = [
        InventoryProduct(
            property_values=(
                InventoryPropertyValue(
                    property_id=513,
                    property_name="Comfort Colors® Colors",
                    value_ids=(100 + index,),
                    values=(name,),
                ),
                InventoryPropertyValue(
                    property_id=514, property_name="Clothing sizes", value_ids=(900,), values=("S",)
                ),
            )
        )
        for index, name in enumerate(["Black", "Blue Jean", "Ivory", "Moss"])
    ]
    etsy.seed_inventory(ETSY_LISTING_ID, Inventory(products=tuple(products)))


def test_variation_images_links_each_colour_to_its_uploaded_image(
    workspace_root: Path, etsy
) -> None:
    _write_renders(workspace_root)
    _seed_inventory(etsy)
    edit_listing(
        workspace_root,
        etsy={
            "title": "<generate>",
            "description": "<generate>",
            "materials": ["cotton"],
            "variation_images": TEMPLATE,
        },
    )
    ctx = _ctx(workspace_root, etsy)

    lock = _apply(ctx, _lock_with_listing_id())

    links = etsy.get_listing_variation_images(SHOP_ID, ETSY_LISTING_ID)
    assert len(links) == 4
    by_value_id = {link.value_id: link.image_id for link in links}
    black_image_id = lock.remote["etsy_image_ids"][f"{TEMPLATE}:black"]
    assert by_value_id[100] == black_image_id
    assert lock.applied["etsy_media"]["variation_images"]["black"] == f"{TEMPLATE}:black"


def test_no_matching_colour_property_skips_the_feature_without_failing(
    workspace_root: Path, etsy
) -> None:
    """No inventory seeded at all -- decision 6's "reports and does nothing"."""
    _write_renders(workspace_root)
    edit_listing(
        workspace_root,
        etsy={
            "title": "<generate>",
            "description": "<generate>",
            "materials": ["cotton"],
            "variation_images": TEMPLATE,
        },
    )
    ctx = _ctx(workspace_root, etsy)

    _apply(ctx, _lock_with_listing_id())

    assert etsy.get_listing_variation_images(SHOP_ID, ETSY_LISTING_ID) == []

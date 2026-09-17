"""The `publish` stage, against in-memory clients (A4).

Run beside `printify_product` in the same pipeline throughout: publishing is
meaningless without a product to publish, and the interesting case -- a first
`apply` that creates the product and publishes it in one run -- only exists
because A26 threads the product id `printify_product` just minted into
`publish`'s own `apply` moments later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, StageState, build_plan
from etsy_listings.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.engine.stages.publish import (
    PublishStage,
    PublishTimeoutError,
    PublishWithoutProductError,
)

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    a_lock,
    edit_listing,
    set_copy,
    set_shop_id,
    write_design,
)

BLUEPRINT = Blueprint(
    id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
)
PROVIDER = PrintProvider(id=29, title="Monster Digital")
COLOURS = ["Black", "Blue Jean", "Ivory", "Moss"]
SIZES = ["S", "M", "L", "XL", "XXL", "XXXL"]
SHOP_ID = 28819281
PRINT_AREA = (4500, 5400)
FIRST_FAKE_PRODUCT_ID = "fake-product-1"
"""`FakePrintifyClient` mints ids as `fake-product-{n}`, counting from one per
instance -- predictable enough that a test can seed `publish_external` for
the product a fresh fake is about to create, before it exists."""

ETSY_LISTING_ID = 4572550919
ETSY_LISTING_HANDLE = "https://www.etsy.com/listing/4572550919/probe"


def _variants() -> VariantSet:
    placeholder = PrintAreaPlaceholder(position="front", width=PRINT_AREA[0], height=PRINT_AREA[1])
    return VariantSet(
        variants=tuple(
            Variant(
                id=1000 + colour_index * 10 + size_index,
                title=f"{colour} / {size}",
                options=VariantOptions(color=colour, size=size),
                placeholders=(placeholder,),
            )
            for colour_index, colour in enumerate(COLOURS)
            for size_index, size in enumerate(SIZES)
        )
    )


@pytest.fixture
def catalog() -> FakeCatalogClient:
    return FakeCatalogClient(
        blueprints=[BLUEPRINT],
        providers_by_blueprint={706: [PROVIDER]},
        variants_by_key={(706, 29): _variants()},
    )


@pytest.fixture
def printify() -> FakePrintifyClient:
    client = FakePrintifyClient([Shop(id=SHOP_ID, title="My new store")])
    # Seeded before the product exists: `publish` on this id will attach
    # `external` and clear `is_locked` in the same read, mirroring a publish
    # that cleared cleanly.
    client.publish_external[FIRST_FAKE_PRODUCT_ID] = ProductExternal(
        id=str(ETSY_LISTING_ID), handle=ETSY_LISTING_HANDLE
    )
    return client


@pytest.fixture
def root(workspace_root: Path) -> Path:
    set_shop_id(workspace_root, SHOP_ID)
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")
    write_design(workspace_root, PRINT_AREA)
    return workspace_root


def _ctx(root: Path, catalog: FakeCatalogClient, printify: FakePrintifyClient) -> RunContext:
    return a_context(root, catalog=catalog, printify=printify)


def _instant_stage() -> PublishStage:
    """A poll that never actually waits -- `sleep` is a no-op, so tests run at
    full speed whether the fake unlocks on the first check or the fifth."""
    return PublishStage(sleep=lambda seconds: None)


def _stages() -> list:
    return [PrintifyProductStage(), _instant_stage()]


def _plan(ctx: RunContext, lock: Lockfile) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, _stages())


def _apply(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, _plan(ctx, lock), lock)


def _publish_plan(ctx: RunContext, lock: Lockfile) -> StagePlan:
    return _plan(ctx, lock).plan.stage_plans[1]


# -------------------------------------------------- first apply, nothing to a listing


def test_a_first_apply_creates_the_product_and_publishes_it_in_one_run(
    root, catalog, printify
) -> None:
    """The case A26 exists for: `printify_product` mints a product id in its
    own `apply`, and `publish`'s `apply`, later in the same run, has to see
    it -- there is no lockfile on disk yet for it to come from."""
    ctx = _ctx(root, catalog, printify)

    result = _apply(ctx, a_lock())

    assert result.remote["etsy_listing_id"] == ETSY_LISTING_ID
    assert result.remote["etsy_listing_handle"] == ETSY_LISTING_HANDLE
    assert printify.published, "publish.json was actually called"


def test_the_first_plan_says_it_will_publish(root, catalog, printify) -> None:
    stage_plan = _publish_plan(_ctx(root, catalog, printify), a_lock())

    assert stage_plan.will_run
    assert "first time" in (stage_plan.reason or "")


def test_planning_touches_no_remote_state_with_no_product_id(root, catalog, printify) -> None:
    _plan(_ctx(root, catalog, printify), a_lock())

    assert printify.shops_calls == 0


# ------------------------------------------------------------------------ no-op


def test_a_second_apply_with_nothing_changed_is_a_no_op(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    published_count = len(printify.published)

    stage_plan = _publish_plan(ctx, lock)

    assert stage_plan.will_run is False
    assert len(printify.published) == published_count, "planning must not publish"


def test_a_second_apply_with_nothing_changed_does_not_republish(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    published_count = len(printify.published)

    _apply(ctx, lock)

    assert len(printify.published) == published_count


# ------------------------------------------------------------- variant changes


def test_a_changed_price_triggers_a_republish(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(
        root,
        prices={
            "S": "399 NOK",
            "M": "399 NOK",
            "L": "399 NOK",
            "XL": "409 NOK",
            "XXL": "419 NOK",
            "XXXL": "429 NOK",
        },
    )

    stage_plan = _publish_plan(ctx, lock)

    assert stage_plan.will_run
    assert "differ" in (stage_plan.reason or "")


# --------------------------------------------------------------------- timeout


def test_a_publish_that_never_unlocks_times_out(root, catalog, printify) -> None:
    """A second fake, this one never seeded with `publish_external`, so its
    product stays locked forever -- the shape of a genuinely stuck publish."""
    stuck = FakePrintifyClient([Shop(id=SHOP_ID, title="My new store")])
    ctx = _ctx(root, catalog, stuck)
    fast_clock = iter([0.0, 700.0]).__next__
    stage = PublishStage(sleep=lambda seconds: None, now=fast_clock, poll_ceiling=600.0)

    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), [PrintifyProductStage()]), a_lock())
    planned = build_plan(ctx, LISTING, lock, [stage])

    with pytest.raises(PublishTimeoutError):
        execute(ctx, planned, lock)


def test_publishing_without_a_product_id_fails_loudly(root, catalog, printify) -> None:
    """Should never happen through the real pipeline -- `printify_product`
    runs first -- but a wiring mistake must not publish a phantom product."""
    ctx = _ctx(root, catalog, printify)
    stage = _instant_stage()
    desired = stage.desired(ctx, LISTING, None)
    stage_plan = StagePlan(stage=stage.name, will_run=True)
    planned = PlannedRun(
        plan=Plan(listing=LISTING, is_live=False, etsy_listing_id=None, stage_plans=(stage_plan,)),
        states=(
            StageState(
                stage=stage, desired=desired, applied=None, live=None, stage_plan=stage_plan
            ),
        ),
    )

    with pytest.raises(PublishWithoutProductError):
        execute(ctx, planned, a_lock())


# ------------------------------------------------------------------ below cost


def test_a_price_below_cost_blocks_with_no_run(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(
        root,
        prices={
            "S": "1 NOK",
            "M": "1 NOK",
            "L": "1 NOK",
            "XL": "1 NOK",
            "XXL": "1 NOK",
            "XXXL": "1 NOK",
        },
    )

    stage_plan = _publish_plan(ctx, lock)

    assert stage_plan.will_run is False
    # `blocked`, not `reason`: a stage that will not run reports a refusal, and
    # `reason` is only rendered for stages that *do* run -- which is how this
    # check shipped invisible, under a plan reading "No changes."
    assert "below" in (stage_plan.blocked or "").lower()
    assert stage_plan.reason is None


def test_the_snapshot_names_every_below_cost_variant(root, catalog, printify) -> None:
    """A30: the price table's red marker reads this, not a second copy of
    `_below_cost`'s own rule."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    edit_listing(
        root,
        prices={
            "S": "1 NOK",
            "M": "1 NOK",
            "L": "1 NOK",
            "XL": "1 NOK",
            "XXL": "1 NOK",
            "XXXL": "1 NOK",
        },
    )

    stage_plan = _publish_plan(ctx, lock)

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert len(snapshot.below_cost) == len(COLOURS) * len(SIZES)
    row = next(r for r in snapshot.below_cost if r.colour == "black" and r.size == "S")
    assert str(row.price) == "1 NOK"
    assert str(row.cost) == "13.04 USD"


def test_a_stage_that_will_run_has_no_below_cost_rows(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(
        root,
        prices={
            "S": "399 NOK",
            "M": "399 NOK",
            "L": "399 NOK",
            "XL": "409 NOK",
            "XXL": "419 NOK",
            "XXXL": "429 NOK",
        },
    )

    stage_plan = _publish_plan(ctx, lock)

    assert stage_plan.snapshot is not None
    assert stage_plan.snapshot.below_cost == ()

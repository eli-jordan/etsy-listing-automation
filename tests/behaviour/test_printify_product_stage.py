"""The `printify_product` stage, against in-memory clients (A4).

What is asserted is behaviour Printify actually has: the product comes back
carrying variants nobody asked for, an update merges rather than replaces, and
creating twice is not prevented by anything on the server. The fake models
those, so a stage that passes here is not passing because the fake was kind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Shop,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import PriceChange
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun, build_plan
from etsy_listings.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.engine.stages.render import RenderStage

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
STAGE = PrintifyProductStage()
PRINT_AREA = (4500, 5400)
"""The profile's front print area. A design at exactly this size passes the
resolution gate; anything smaller is what `write_design` is asked for when a
test wants the refusal."""
TOO_SMALL = (120, 140)


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
    return FakePrintifyClient([Shop(id=SHOP_ID, title="My new store")])


@pytest.fixture
def root(workspace_root: Path) -> Path:
    """The fixture workspace, made Phase-2 ready: a Printify shop id, real
    copy instead of the fixture's blank placeholders, and a design at print
    resolution.

    All three are things `plan` refuses without, and each has its own test
    below -- these are the *passing* values."""
    set_shop_id(workspace_root, SHOP_ID)
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")
    write_design(workspace_root, PRINT_AREA)
    return workspace_root


def _ctx(root: Path, catalog: FakeCatalogClient, printify: FakePrintifyClient) -> RunContext:
    return a_context(root, catalog=catalog, printify=printify)


def _plan(ctx: RunContext, lock: Lockfile) -> PlannedRun:
    return build_plan(ctx, LISTING, lock, [STAGE])


def _stage_plan(ctx: RunContext, lock: Lockfile):
    return _plan(ctx, lock).plan.stage_plans[0]


def _apply(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, _plan(ctx, lock), lock)


# ------------------------------------------------------------------ creating


def test_the_first_plan_says_it_will_create_a_product(root, catalog, printify) -> None:
    stage_plan = _stage_plan(_ctx(root, catalog, printify), a_lock())

    assert stage_plan.will_run
    assert "create" in (stage_plan.reason or "").lower()


def test_planning_touches_no_remote_state(root, catalog, printify) -> None:
    """`plan` is read-only, and with no product id there is nothing even to
    read -- so it must not ask, or a fresh workspace needs a token to run a
    command that changes nothing."""
    _plan(_ctx(root, catalog, printify), a_lock())

    assert printify.created == []
    assert printify.products == {}


def test_apply_creates_the_product_with_the_whole_matrix(root, catalog, printify) -> None:
    lock = _apply(_ctx(root, catalog, printify), a_lock())

    assert len(printify.created) == 1
    spec = printify.created[0]
    assert len(spec.variants) == len(COLOURS) * len(SIZES)
    assert lock.remote["printify_product_id"] == "fake-product-1"


FIXTURE_PRICES_MINOR = {
    "S": 34900,
    "M": 34900,
    "L": 34900,
    "XL": 35900,
    "XXL": 36900,
    "XXXL": 37900,
}
"""``listing.yaml``'s ``prices:`` in NOK øre. Transcribed from the fixture, not
computed from it -- a helper that multiplied by 100 the way the code does would
agree with a broken conversion."""


def test_prices_reach_printify_as_minor_units_of_the_shop_currency(root, catalog, printify) -> None:
    """PRD 39/40: NOK goes to Printify verbatim. `349 NOK` is `34900`, not a
    converted USD figure -- no rate reaches `apply`, and none reaches a hash.

    Asserted per variant rather than as "34900 turns up somewhere in the
    values". The failure worth catching is a price landing on the wrong *size*,
    and every size shares a price with at least one other, so a membership test
    cannot see it: the whole matrix could be priced at 349 and still pass.
    """
    _apply(_ctx(root, catalog, printify), a_lock())

    by_id = {variant.id: variant.options for variant in _variants().variants}
    priced = {
        (by_id[variant_id].color, by_id[variant_id].size): price
        for variant_id, price in printify.created[0].variants.items()
    }

    assert priced == {
        (colour, size): FIXTURE_PRICES_MINOR[size] for colour in COLOURS for size in SIZES
    }


# ------------------------------------------------------------------ snapshot


def test_the_snapshot_names_every_desired_variant(root, catalog, printify) -> None:
    """A30: the before/after review needs the whole matrix, colour and size
    named, not the raw variant ids `apply` sends."""
    stage_plan = _stage_plan(_ctx(root, catalog, printify), a_lock())

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert len(snapshot.desired) == 4 * len(SIZES), "the listing's own four colours, every size"
    assert snapshot.live == (), "nothing has been created yet"
    row = next(r for r in snapshot.desired if r.colour == "black" and r.size == "S")
    assert str(row.price) == "349 NOK"


def test_the_snapshot_names_every_live_variant_once_the_product_exists(
    root, catalog, printify
) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    stage_plan = _stage_plan(ctx, lock)

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert len(snapshot.live) == 4 * len(SIZES)
    row = next(r for r in snapshot.live if r.colour == "black" and r.size == "S")
    assert str(row.price) == "349 NOK"


def test_the_snapshot_skips_a_live_variant_the_current_resolution_dropped(
    root, catalog, printify
) -> None:
    """A garment change is blocked (PRD 37), but dropping a *colour* is not
    -- so a live variant the current resolution no longer names is real, and
    the only thing to do with it is leave it off rather than guess a name."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(
        root,
        colors=["black", "blue-jean", "ivory"],
        media=[{"template": "flat-lay-01", "colour": c} for c in ("black", "blue-jean", "ivory")],
    )

    stage_plan = _stage_plan(ctx, lock)

    snapshot = stage_plan.snapshot
    assert snapshot is not None
    assert len(snapshot.desired) == 3 * len(SIZES)
    assert len(snapshot.live) == 3 * len(SIZES), "moss is still live but no longer named here"
    assert all(row.colour != "moss" for row in snapshot.live)


def test_a_blocked_stage_has_no_snapshot(workspace_root: Path, catalog, printify) -> None:
    """No desired document exists for a blocked stage to be a snapshot of --
    it must not fabricate one from whatever it had before refusing."""
    stage_plan = _stage_plan(_ctx(workspace_root, catalog, printify), a_lock())

    assert stage_plan.blocked is not None
    assert stage_plan.snapshot is None


def test_the_design_is_uploaded_once_and_placed_centred(root, catalog, printify) -> None:
    _apply(_ctx(root, catalog, printify), a_lock())

    assert len(printify.uploads) == 1
    placed = printify.created[0].print_areas[0].placeholders[0].images[0]
    assert (placed.x, placed.y, placed.scale, placed.angle) == (0.5, 0.5, 1.0, 0)


def test_the_print_area_uses_the_profiles_placeholder(root, catalog, printify) -> None:
    _apply(_ctx(root, catalog, printify), a_lock())

    assert printify.created[0].print_areas[0].placeholders[0].position == "front"


def test_the_upload_id_is_remembered_so_a_re_run_does_not_ship_it_again(
    root, catalog, printify
) -> None:
    """Uploads are content-addressed, so re-uploading is safe -- and wasteful,
    since it still ships the megabytes."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    assert lock.remote["printify_upload_ids"]

    calls_before = len(printify.uploads)
    set_copy(root, title="Take A Hike Tee v2", description="A retro sunset.")
    _apply(ctx, lock)

    assert len(printify.uploads) == calls_before, "same bytes, no second upload"


# ------------------------------------------------------------- idempotency


def test_a_second_plan_reports_no_changes(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    stage_plan = _stage_plan(ctx, lock)

    assert not stage_plan.will_run
    assert stage_plan.changes == ()


def test_a_second_apply_writes_nothing(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    _apply(ctx, lock)

    assert len(printify.created) == 1
    assert printify.updated == []


def test_the_product_id_never_reaches_the_hash(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    first = _apply(ctx, a_lock())
    second = _apply(ctx, first)

    assert first.input_hash() == second.input_hash()


# ----------------------------------------------------------------- updating


def test_a_price_change_is_reported_and_applied(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(root, prices={**dict.fromkeys(SIZES, "349 NOK"), "S": "399 NOK"})
    planned = _plan(ctx, lock)

    assert any(isinstance(change, PriceChange) for change in planned.plan.stage_plans[0].changes)

    execute(ctx, planned, lock)
    assert 39900 in printify.updated[0].variants.values()


def test_dropping_a_colour_disables_its_variants_explicitly(root, catalog, printify) -> None:
    """Omission means "no opinion" to Printify, not "off". A dropped colour
    that is merely left out of the payload keeps selling."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(
        root,
        colors=["black", "blue-jean", "ivory"],
        media=[{"template": "flat-lay-01", "colour": c} for c in ("black", "blue-jean")],
    )
    lock = _apply(ctx, lock)

    product = printify.products["fake-product-1"]
    moss_ids = {v.id for v in _variants().variants if v.options.color == "Moss"}
    still_enabled = set(product.enabled_variants())
    assert not (moss_ids & still_enabled)


def test_an_update_reads_the_product_before_writing_it(root, catalog, printify) -> None:
    """The coverage rule makes the read mandatory: an update's print areas
    must name every variant the product has, which only a read knows."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())

    edit_listing(root, prices={**dict.fromkeys(SIZES, "359 NOK")})
    _apply(ctx, lock)

    assert printify.updated, "it updated rather than created a second product"
    assert len(printify.created) == 1


# --------------------------------------------------------------- the gates


def test_an_empty_title_blocks_the_stage(root, catalog, printify) -> None:
    set_copy(root, title="", description="A retro sunset.")

    stage_plan = _stage_plan(_ctx(root, catalog, printify), a_lock())

    assert stage_plan.will_run is False
    assert "empty" in (stage_plan.blocked or "")


def test_a_common_copy_ref_composes_into_the_product_description(root, catalog, printify) -> None:
    """The product carries the listing's own composed description (PRD 44);
    it must be exactly what `Workspace.compose_description` produces, not the
    raw lead alone."""
    common_copy = root / "common-copy"
    common_copy.mkdir()
    (common_copy / "comfort-colors.md").write_text(
        "---\ntitle: Comfort Colors\ntargets: [description]\n---\n"
        "Printed to order on a heavyweight shirt.",
        encoding="utf-8",
    )
    edit_listing(
        root,
        etsy={
            "title": "Take A Hike Tee",
            "description": {"lead": "A retro sunset.", "ref": "common-copy/comfort-colors.md"},
        },
    )

    lock = _apply(_ctx(root, catalog, printify), a_lock())

    spec = printify.created[0]
    assert spec.description == "A retro sunset.\n\nPrinted to order on a heavyweight shirt."
    assert lock.remote["printify_product_id"] == "fake-product-1"


def test_a_missing_common_copy_ref_blocks_the_stage(root, catalog, printify) -> None:
    edit_listing(
        root,
        etsy={
            "title": "Take A Hike Tee",
            "description": {"lead": "A retro sunset.", "ref": "common-copy/missing.md"},
        },
    )

    stage_plan = _stage_plan(_ctx(root, catalog, printify), a_lock())

    assert stage_plan.will_run is False
    assert "common-copy/missing.md" in (stage_plan.blocked or "")


def test_an_undersized_design_blocks_the_stage(root, catalog, printify) -> None:
    write_design(root, TOO_SMALL)

    stage_plan = _stage_plan(_ctx(root, catalog, printify), a_lock())

    assert stage_plan.will_run is False
    assert "too small" in (stage_plan.blocked or "")


def test_a_changed_garment_blocks_the_stage(root, catalog, printify) -> None:
    """And blocks *before* anything is sent, since Printify would answer 200
    and change nothing."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    lock.applied["printify_product"]["blueprint_id"] = 6

    stage_plan = _stage_plan(ctx, lock)

    assert stage_plan.will_run is False
    assert "different garment" in (stage_plan.blocked or "")


def test_a_blocked_stage_sends_nothing(root, catalog, printify) -> None:
    """The half that has to stay hard. A refusal is now a value rather than an
    exception, so the thing that stops the payload is `will_run=False` and
    `execute` honouring it -- not the traceback that used to."""
    ctx = _ctx(root, catalog, printify)
    write_design(root, TOO_SMALL)

    _apply(ctx, a_lock())

    assert printify.created == []
    assert not printify.uploads


def test_a_refusal_does_not_cost_the_other_stages_their_plan(root, catalog, printify) -> None:
    """The reason a gate returns rather than raises. Planning the whole
    pipeline used to end at the first refusal, so an undersized design cost
    the user the render stage's plan as well and printed one line where a
    listing's worth of intent belonged."""
    write_design(root, TOO_SMALL)
    stages = [RenderStage(), STAGE]

    plan = build_plan(_ctx(root, catalog, printify), LISTING, a_lock(), stages).plan

    by_stage = {sp.stage: sp for sp in plan.stage_plans}
    assert by_stage["render"].will_run is True, "the local stage still reports its work"
    assert by_stage["printify_product"].blocked


def test_a_colour_the_catalog_does_not_offer_is_refused(root, catalog, printify) -> None:
    edit_listing(
        root,
        colors=["black", "chartreuse"],
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )

    with pytest.raises(ValueError, match="chartreuse"):
        _plan(_ctx(root, catalog, printify), a_lock())


# ------------------------------------------------- the duplicate-create guard


def test_a_lost_lockfile_adopts_the_existing_product_rather_than_duplicating(
    root, catalog, printify
) -> None:
    """PRD 48. Create succeeded, the process died before the lockfile was
    written, and the next run has no id. Creating again would leave two
    products for one listing, and Printify prevents nothing."""
    ctx = _ctx(root, catalog, printify)
    _apply(ctx, a_lock())

    _apply(ctx, a_lock())  # a fresh lockfile: the crash case

    assert len(printify.created) == 1, "it found the product it had already made"


def test_the_adopted_product_id_is_recorded(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    _apply(ctx, a_lock())

    lock = _apply(ctx, a_lock())

    assert lock.remote["printify_product_id"] == "fake-product-1"


def test_a_product_deleted_in_printify_is_created_again(root, catalog, printify) -> None:
    """The other direction: the lockfile names a product that is gone, which
    means create, not crash."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    printify.products.clear()

    _apply(ctx, lock)

    assert len(printify.created) == 2


# ------------------------------------------------------------------- drift


def test_a_title_changed_in_printify_is_reported_as_drift(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    live = printify.products["fake-product-1"]
    printify.products["fake-product-1"] = live.model_copy(update={"title": "Changed by hand"})

    stage_plan = _stage_plan(ctx, lock)

    assert any("title" in d.path for d in stage_plan.drift)


def test_a_product_that_came_back_visible_is_reported(root, catalog, printify) -> None:
    """The tripwire. Whether a publish lands as a draft is decided outside
    this tool, so a managed product turning visible is the one signal that
    something changed the setting that matters."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, a_lock())
    live = printify.products["fake-product-1"]
    printify.products["fake-product-1"] = live.model_copy(update={"visible": True})

    stage_plan = _stage_plan(ctx, lock)

    assert any("visible" in d.path for d in stage_plan.drift)


# ------------------------------------------------------- missing cells (46)


def test_a_discontinued_cell_is_reported_rather_than_fatal(root, catalog, printify) -> None:
    """PRD 46. Printify dropped `Moss / XXXL`; the listing is not wrong for
    having asked, and the product is created without it."""
    dropped = VariantSet(
        variants=tuple(
            v
            for v in _variants().variants
            if not (v.options.color == "Moss" and v.options.size == "XXXL")
        )
    )
    catalog._variants_by_key[(706, 29)] = dropped  # noqa: SLF001 - fixture surgery

    stage_plan = _stage_plan(_ctx(root, catalog, printify), a_lock())

    # The exact sentence, not "Moss appears somewhere in the actions". A
    # report that names the count but not the cell, or the cell but not which
    # size, is the report this test is supposed to be checking -- and either
    # would satisfy a substring search for "Moss".
    skipped = [a.description for a in stage_plan.actions if a.description.startswith("skip ")]
    assert skipped == ["skip 1 colour/size combination(s) this garment no longer offers: moss/XXXL"]
    # ...and the product is still created, without the cell.
    assert any(a.description.startswith("create ") for a in stage_plan.actions)

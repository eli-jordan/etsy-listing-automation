"""The `printify_product` stage, against in-memory clients (A4).

What is asserted is behaviour Printify actually has: the product comes back
carrying variants nobody asked for, an update merges rather than replaces, and
creating twice is not prevented by anything on the server. The fake models
those, so a stage that passes here is not passing because the fake was kind.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image

from etsy_listings import __about__
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.clients.printify.models import Shop
from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import Plan, PriceChange
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stages.gates import (
    DesignResolutionError,
    GarmentChangedError,
    UnresolvedCopyError,
)
from etsy_listings.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.workspace.workspace import Workspace

BLUEPRINT = Blueprint(
    id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
)
PROVIDER = PrintProvider(id=29, title="Monster Digital")
COLOURS = ["Black", "Blue Jean", "Ivory", "Moss"]
SIZES = ["S", "M", "L", "XL", "XXL", "XXXL"]
SHOP_ID = 28819281
STAGE = PrintifyProductStage()
LISTING = "take-a-hike"


def _variants() -> VariantSet:
    placeholder = PrintAreaPlaceholder(position="front", width=4500, height=5400)
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
    copy instead of `<generate>` sentinels, and a design at print resolution.

    All three are things `plan` refuses without, and each has its own test
    below -- these are the *passing* values."""
    shop = workspace_root / "shop.yaml"
    document = yaml.safe_load(shop.read_text(encoding="utf-8"))
    document["printify"] = {"shop_id": SHOP_ID}
    shop.write_text(yaml.safe_dump(document), encoding="utf-8")

    _write_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")
    _write_design(workspace_root, (4500, 5400))
    return workspace_root


def _write_copy(root: Path, *, title: str, description: str) -> None:
    path = root / "listings" / LISTING / "listing.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["etsy"]["title"] = title
    document["etsy"]["description"] = description
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def _write_listing(root: Path, **updates: object) -> None:
    path = root / "listings" / LISTING / "listing.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.update(updates)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def _write_design(root: Path, size: tuple[int, int]) -> None:
    Image.new("RGBA", size, (10, 20, 30, 255)).save(root / "designs" / "take-a-hike.png")


def _ctx(root: Path, catalog: FakeCatalogClient, printify: FakePrintifyClient) -> RunContext:
    return RunContext(
        workspace=Workspace.discover(root_override=root), catalog=catalog, printify=printify
    )


def _lock(**kwargs: object) -> Lockfile:
    return Lockfile(tool_version=__about__.VERSION, applied_at="2026-09-08T00:00:00Z", **kwargs)


def _plan(ctx: RunContext, lock: Lockfile) -> Plan:
    return build_plan(ctx, LISTING, lock, [STAGE])


def _apply(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, _plan(ctx, lock), lock, [STAGE])


# ------------------------------------------------------------------ creating


def test_the_first_plan_says_it_will_create_a_product(root, catalog, printify) -> None:
    plan = _plan(_ctx(root, catalog, printify), _lock())

    stage_plan = plan.stage_plans[0]
    assert stage_plan.will_run
    assert "create" in (stage_plan.reason or "").lower()


def test_planning_touches_no_remote_state(root, catalog, printify) -> None:
    """`plan` is read-only, and with no product id there is nothing even to
    read -- so it must not ask, or a fresh workspace needs a token to run a
    command that changes nothing."""
    _plan(_ctx(root, catalog, printify), _lock())

    assert printify.created == []
    assert printify.products == {}


def test_apply_creates_the_product_with_the_whole_matrix(root, catalog, printify) -> None:
    lock = _apply(_ctx(root, catalog, printify), _lock())

    assert len(printify.created) == 1
    spec = printify.created[0]
    assert len(spec.variants) == len(COLOURS) * len(SIZES)
    assert lock.remote["printify_product_id"] == "fake-product-1"


def test_prices_reach_printify_as_minor_units_of_the_shop_currency(root, catalog, printify) -> None:
    """PRD 39/40: NOK goes to Printify verbatim. `349 NOK` is `34900`, not a
    converted USD figure -- no rate reaches `apply`, and none reaches a hash."""
    _apply(_ctx(root, catalog, printify), _lock())

    assert 34900 in printify.created[0].variants.values()
    assert 37900 in printify.created[0].variants.values(), "XXXL at 379 NOK"


def test_the_design_is_uploaded_once_and_placed_centred(root, catalog, printify) -> None:
    _apply(_ctx(root, catalog, printify), _lock())

    assert len(printify.uploads) == 1
    placed = printify.created[0].print_areas[0].placeholders[0].images[0]
    assert (placed.x, placed.y, placed.scale, placed.angle) == (0.5, 0.5, 1.0, 0)


def test_the_print_area_uses_the_profiles_placeholder(root, catalog, printify) -> None:
    _apply(_ctx(root, catalog, printify), _lock())

    assert printify.created[0].print_areas[0].placeholders[0].position == "front"


def test_the_upload_id_is_remembered_so_a_re_run_does_not_ship_it_again(
    root, catalog, printify
) -> None:
    """Uploads are content-addressed, so re-uploading is safe -- and wasteful,
    since it still ships the megabytes."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())

    assert lock.remote["printify_upload_ids"]

    calls_before = len(printify.uploads)
    _write_copy(root, title="Take A Hike Tee v2", description="A retro sunset.")
    _apply(ctx, lock)

    assert len(printify.uploads) == calls_before, "same bytes, no second upload"


# ------------------------------------------------------------- idempotency


def test_a_second_plan_reports_no_changes(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())

    plan = _plan(ctx, lock)

    assert not plan.stage_plans[0].will_run
    assert plan.stage_plans[0].changes == ()


def test_a_second_apply_writes_nothing(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())

    _apply(ctx, lock)

    assert len(printify.created) == 1
    assert printify.updated == []


def test_the_product_id_never_reaches_the_hash(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    first = _apply(ctx, _lock())
    second = _apply(ctx, first)

    assert first.input_hash() == second.input_hash()


# ----------------------------------------------------------------- updating


def test_a_price_change_is_reported_and_applied(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())

    _write_listing(root, prices={**dict.fromkeys(SIZES, "349 NOK"), "S": "399 NOK"})
    plan = _plan(ctx, lock)

    assert any(isinstance(change, PriceChange) for change in plan.stage_plans[0].changes)

    execute(ctx, plan, lock, [STAGE])
    assert 39900 in printify.updated[0].variants.values()


def test_dropping_a_colour_disables_its_variants_explicitly(root, catalog, printify) -> None:
    """Omission means "no opinion" to Printify, not "off". A dropped colour
    that is merely left out of the payload keeps selling."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())

    _write_listing(root, colors=["black", "blue-jean", "ivory"])
    _write_listing(
        root, media=[{"template": "flat-lay-01", "colour": c} for c in ("black", "blue-jean")]
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
    lock = _apply(ctx, _lock())

    _write_listing(root, prices={**dict.fromkeys(SIZES, "359 NOK")})
    _apply(ctx, lock)

    assert printify.updated, "it updated rather than created a second product"
    assert len(printify.created) == 1


# --------------------------------------------------------------- the gates


def test_a_generate_sentinel_is_refused_at_plan_time(root, catalog, printify) -> None:
    _write_copy(root, title="<generate>", description="A retro sunset.")

    with pytest.raises(UnresolvedCopyError):
        _plan(_ctx(root, catalog, printify), _lock())


def test_an_undersized_design_is_refused_at_plan_time(root, catalog, printify) -> None:
    _write_design(root, (120, 140))

    with pytest.raises(DesignResolutionError):
        _plan(_ctx(root, catalog, printify), _lock())


def test_a_changed_garment_is_refused_at_plan_time(root, catalog, printify) -> None:
    """And refused *before* anything is sent, since Printify would answer 200
    and change nothing."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())
    lock.applied["printify_product"]["blueprint_id"] = 6

    with pytest.raises(GarmentChangedError):
        _plan(ctx, lock)


def test_a_colour_the_catalog_does_not_offer_is_refused(root, catalog, printify) -> None:
    _write_listing(
        root,
        colors=["black", "chartreuse"],
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )

    with pytest.raises(ValueError, match="chartreuse"):
        _plan(_ctx(root, catalog, printify), _lock())


# ------------------------------------------------- the duplicate-create guard


def test_a_lost_lockfile_adopts_the_existing_product_rather_than_duplicating(
    root, catalog, printify
) -> None:
    """PRD 48. Create succeeded, the process died before the lockfile was
    written, and the next run has no id. Creating again would leave two
    products for one listing, and Printify prevents nothing."""
    ctx = _ctx(root, catalog, printify)
    _apply(ctx, _lock())

    _apply(ctx, _lock())  # a fresh lockfile: the crash case

    assert len(printify.created) == 1, "it found the product it had already made"


def test_the_adopted_product_id_is_recorded(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    _apply(ctx, _lock())

    lock = _apply(ctx, _lock())

    assert lock.remote["printify_product_id"] == "fake-product-1"


def test_a_product_deleted_in_printify_is_created_again(root, catalog, printify) -> None:
    """The other direction: the lockfile names a product that is gone, which
    means create, not crash."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())
    printify.products.clear()

    _apply(ctx, lock)

    assert len(printify.created) == 2


# ------------------------------------------------------------------- drift


def test_a_title_changed_in_printify_is_reported_as_drift(root, catalog, printify) -> None:
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())
    live = printify.products["fake-product-1"]
    printify.products["fake-product-1"] = live.model_copy(update={"title": "Changed by hand"})

    plan = _plan(ctx, lock)

    assert any("title" in d.path for d in plan.stage_plans[0].drift)


def test_a_product_that_came_back_visible_is_reported(root, catalog, printify) -> None:
    """The tripwire. Whether a publish lands as a draft is decided outside
    this tool, so a managed product turning visible is the one signal that
    something changed the setting that matters."""
    ctx = _ctx(root, catalog, printify)
    lock = _apply(ctx, _lock())
    live = printify.products["fake-product-1"]
    printify.products["fake-product-1"] = live.model_copy(update={"visible": True})

    plan = _plan(ctx, lock)

    assert any("visible" in d.path for d in plan.stage_plans[0].drift)


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

    plan = _plan(_ctx(root, catalog, printify), _lock())

    actions = " ".join(a.description for a in plan.stage_plans[0].actions)
    assert "Moss" in actions or "moss" in actions
    assert "XXXL" in actions

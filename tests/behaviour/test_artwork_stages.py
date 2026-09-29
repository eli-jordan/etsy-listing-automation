"""Artwork resolution through the stages (A35): what the render and Printify
stages do with a listing's ``design:`` map.

Both stages ask `config/artwork.py`, and both key an artwork group by the
resolved file's *content hash* -- so a reshaped map that prints the same file
on every garment plans nothing, and a configuration that cannot resolve is a
``Blocked`` stage, never a ``ValueError`` that ends a ``--all`` batch.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient
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
from etsy_listings.engine.change import StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.run import plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.etsy_media import EtsyMediaStage
from etsy_listings.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.engine.stages.render import RenderStage

from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import (
    a_context,
    a_lock,
    copy_listing,
    edit_garment_profile,
    edit_listing,
    set_copy,
    set_etsy_shop_id,
    set_shop_id,
    write_design,
)

PROFILE = "comfort-colors-1717"
TONES = {"black": "dark", "blue-jean": "dark", "ivory": "light", "moss": "dark"}
DESIGN = "designs/take-a-hike.png"
ETSY_LISTING_ID = 4572550919
ETSY_SHOP_ID = 12345678


def _render_plan(ctx: RunContext, lock: Lockfile) -> StagePlan:
    return build_plan(ctx, LISTING, lock, [RenderStage()]).plan.stage_plans[0]


def _write_template(root: Path, name: str, document: dict[str, object]) -> None:
    directory = root / "mockup-templates" / name
    directory.mkdir(parents=True)
    (directory / "template.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    shutil.copy(root / "mockup-templates" / "flat-lay-01" / "black.png", directory / "scene.png")


BOX = [
    {"x": 10.0, "y": 10.0},
    {"x": 90.0, "y": 10.0},
    {"x": 90.0, "y": 90.0},
    {"x": 10.0, "y": 90.0},
]


# ------------------------------------------------------------------ render


def test_reshaping_the_map_without_changing_a_print_renders_nothing(workspace_root: Path) -> None:
    """The first plan after moving to a light/dark pair holding the same file
    twice: every garment still prints the same bytes, so nothing re-renders."""
    ctx = a_context(workspace_root)
    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), [RenderStage()]), a_lock())

    edit_listing(workspace_root, design={"on-light": DESIGN, "on-dark": DESIGN})

    assert _render_plan(ctx, lock).will_run is False


def test_renaming_the_design_file_renders_nothing(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), [RenderStage()]), a_lock())

    shutil.copy(workspace_root / DESIGN, workspace_root / "designs" / "renamed.png")
    edit_listing(workspace_root, design={"default": "designs/renamed.png"})

    assert _render_plan(ctx, lock).will_run is False


def test_a_colour_that_prints_a_different_file_re_renders(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    lock = execute(ctx, build_plan(ctx, LISTING, a_lock(), [RenderStage()]), a_lock())

    other = workspace_root / "designs" / "moss-special.png"
    other.write_bytes((workspace_root / DESIGN).read_bytes() + b"\x00")
    edit_listing(workspace_root, design={"default": DESIGN, "moss": "designs/moss-special.png"})

    render_plan = _render_plan(ctx, lock)
    assert render_plan.will_run is True
    assert render_plan.reason == "design or template changed"


def test_an_unclassified_colour_blocks_render_naming_the_profile(workspace_root: Path) -> None:
    edit_garment_profile(
        workspace_root, PROFILE, colors={c: t for c, t in TONES.items() if c != "moss"}
    )

    render_plan = _render_plan(a_context(workspace_root), a_lock())

    assert render_plan.blocked is not None
    assert "Moss isn't marked light or dark" in render_plan.blocked
    assert PROFILE in render_plan.blocked


def test_a_needed_slot_left_empty_blocks_render(workspace_root: Path) -> None:
    edit_listing(workspace_root, design={"on-light": None, "on-dark": DESIGN})

    render_plan = _render_plan(a_context(workspace_root), a_lock())

    assert render_plan.blocked is not None
    assert "Ivory is a light shirt" in render_plan.blocked


def test_a_colourless_single_scene_blocks_render_in_light_dark_mode(
    workspace_root: Path,
) -> None:
    _write_template(workspace_root, "lifestyle-01", {"kind": "single", "bounding_box": BOX})
    edit_listing(
        workspace_root,
        design={"on-light": DESIGN, "on-dark": DESIGN},
        media=[{"template": "flat-lay-01", "colour": "black"}, {"template": "lifestyle-01"}],
    )

    render_plan = _render_plan(a_context(workspace_root), a_lock())

    assert render_plan.blocked is not None
    assert "'lifestyle-01' doesn't say which shirt colour it shows" in render_plan.blocked


def test_a_colourless_single_scene_prints_default_in_single_mode(workspace_root: Path) -> None:
    _write_template(workspace_root, "lifestyle-01", {"kind": "single", "bounding_box": BOX})
    edit_listing(workspace_root, media=[{"template": "lifestyle-01"}])

    render_plan = _render_plan(a_context(workspace_root), a_lock())

    assert render_plan.blocked is None
    assert render_plan.will_run is True


def test_a_placement_with_no_colour_blocks_render_in_light_dark_mode(
    workspace_root: Path,
) -> None:
    """A calibrator placement not yet given a colour is not a colour any
    garment profile classifies. Refused, not raised."""
    _write_template(
        workspace_root,
        "chart-02",
        {
            "kind": "multiple",
            "placements": [
                {"colour": "black", "bounding_box": BOX},
                {"colour": "", "bounding_box": BOX},
            ],
        },
    )
    edit_listing(
        workspace_root,
        design={"on-light": DESIGN, "on-dark": DESIGN},
        media=[{"template": "flat-lay-01", "colour": "black"}, {"template": "chart-02"}],
    )

    render_plan = _render_plan(a_context(workspace_root), a_lock())

    assert render_plan.blocked is not None
    assert "chart-02" in render_plan.blocked


def test_multiple_scene_layers_print_each_colours_own_file(workspace_root: Path) -> None:
    """Each placement resolves by the colour it depicts, so a chart showing
    black and moss reads both files when moss has its own design."""
    other = workspace_root / "designs" / "moss-special.png"
    other.write_bytes((workspace_root / DESIGN).read_bytes() + b"\x00")
    edit_listing(
        workspace_root,
        design={"default": DESIGN, "moss": "designs/moss-special.png"},
        media=[{"template": "flat-lay-01", "colour": "black"}, {"template": "colour-chart-01"}],
    )

    render_plan = _render_plan(a_context(workspace_root), a_lock())

    chart = next(a for a in render_plan.actions if a.description == "render colour-chart-01")
    assert chart.inputs[:2] == (DESIGN, "designs/moss-special.png")


def test_an_unresolvable_listing_does_not_stop_the_batch(workspace_root: Path) -> None:
    """PRD 16: a refusal is a blocked stage on its own listing, and ``--all``
    carries on to the next one."""
    copy_listing(workspace_root, "paired")
    edit_listing(workspace_root, "paired", design={"on-light": None, "on-dark": DESIGN})

    ctx = a_context(workspace_root, printify=FakePrintifyClient([]))
    report = plan_listings(ctx, ["paired", LISTING], STAGES)

    assert [outcome.ok for outcome in report.outcomes] == [True, True]
    paired, fixture = (outcome.planned for outcome in report.outcomes)
    assert paired is not None and fixture is not None
    render = {sp.stage: sp for sp in paired.plan.stage_plans}["render"]
    assert render.blocked is not None
    assert {sp.stage: sp for sp in fixture.plan.stage_plans}["render"].will_run is True


def test_the_first_plan_after_upgrade_re_renders_the_same_bytes_and_uploads_nothing(
    workspace_root: Path,
) -> None:
    """A35 changes every render ``input_hash`` once: the recipe now names a
    layer's design by content hash, not by its ``design:`` key. The renders
    come out byte-identical, so the ``outputs`` axis is unchanged and Etsy
    receives nothing (plan, *A35*). The pre-upgrade hash is stood in for by
    any other value -- what matters is that the stage re-runs."""
    set_etsy_shop_id(workspace_root, ETSY_SHOP_ID)
    etsy = FakeEtsyListingClient()
    etsy.seed_listing(ETSY_LISTING_ID, shop_id=ETSY_SHOP_ID)
    ctx = a_context(workspace_root, etsy=etsy)
    stages = [RenderStage(), EtsyMediaStage()]
    first = a_lock(remote={"etsy_listing_id": ETSY_LISTING_ID})
    lock = execute(ctx, build_plan(ctx, LISTING, first, stages), first)
    uploads = len(etsy.uploads)

    render = {**lock.applied["render"], "input_hash": "sha256:written-before-a35"}
    upgraded = lock.model_copy(update={"applied": {**lock.applied, "render": render}})
    planned = build_plan(ctx, LISTING, upgraded, stages)
    by_stage = {sp.stage: sp for sp in planned.plan.stage_plans}
    assert by_stage["render"].will_run is True
    assert by_stage["etsy_media"].will_run is False

    after = execute(ctx, planned, upgraded)

    assert after.outputs == lock.outputs
    assert len(etsy.uploads) == uploads
    assert not any(sp.will_run for sp in build_plan(ctx, LISTING, after, stages).plan.stage_plans)


# ------------------------------------------------------------------ printify

BLUEPRINT = Blueprint(
    id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
)
PROVIDER = PrintProvider(id=29, title="Monster Digital")
COLOURS = ["Black", "Blue Jean", "Ivory", "Moss"]
SIZES = ["S", "M", "L", "XL", "XXL", "XXXL"]
SHOP_ID = 28819281
PRINT_AREA = (4500, 5400)


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


def _upload_id(path: Path) -> str:
    """The fake's content-addressed upload id, which is the real API's rule."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:24]


def _ids(colour_index: int) -> list[int]:
    return [1000 + colour_index * 10 + size_index for size_index in range(len(SIZES))]


@pytest.fixture
def printify() -> FakePrintifyClient:
    return FakePrintifyClient([Shop(id=SHOP_ID, title="My new store")])


@pytest.fixture
def product_ctx(workspace_root: Path, printify: FakePrintifyClient) -> RunContext:
    set_shop_id(workspace_root, SHOP_ID)
    set_copy(workspace_root, title="Take A Hike Tee", description="A retro sunset.")
    write_design(workspace_root, PRINT_AREA)
    catalog = FakeCatalogClient(
        blueprints=[BLUEPRINT],
        providers_by_blueprint={706: [PROVIDER]},
        variants_by_key={(706, 29): _variants()},
    )
    return a_context(workspace_root, catalog=catalog, printify=printify)


def _product_plan(ctx: RunContext, lock: Lockfile) -> StagePlan:
    return build_plan(ctx, LISTING, lock, [PrintifyProductStage()]).plan.stage_plans[0]


def _apply_product(ctx: RunContext, lock: Lockfile) -> Lockfile:
    return execute(ctx, build_plan(ctx, LISTING, lock, [PrintifyProductStage()]), lock)


def test_two_files_are_two_print_areas_with_their_own_variants(
    workspace_root: Path, product_ctx: RunContext, printify: FakePrintifyClient
) -> None:
    dark_ink = workspace_root / DESIGN
    light_ink = workspace_root / "designs" / "light-ink.png"
    light_ink.write_bytes(dark_ink.read_bytes() + b"\x00")
    edit_listing(workspace_root, design={"on-light": DESIGN, "on-dark": "designs/light-ink.png"})

    _apply_product(product_ctx, a_lock())

    [created] = printify.created
    areas = {
        area.placeholders[0].images[0].id: sorted(area.variant_ids) for area in created.print_areas
    }
    assert len(printify.uploads) == 2
    assert areas == {
        _upload_id(dark_ink): _ids(2),
        _upload_id(light_ink): sorted(_ids(0) + _ids(1) + _ids(3)),
    }


def test_two_names_for_one_file_are_one_print_area(
    workspace_root: Path, product_ctx: RunContext, printify: FakePrintifyClient
) -> None:
    """Groups are keyed by content, not by ref: identical bytes under two
    names print as one area, and no print area shares an image with another."""
    shutil.copy(workspace_root / DESIGN, workspace_root / "designs" / "same.png")
    edit_listing(workspace_root, design={"on-light": DESIGN, "on-dark": "designs/same.png"})

    _apply_product(product_ctx, a_lock())

    [created] = printify.created
    [area] = created.print_areas
    assert sorted(area.variant_ids) == sorted(_ids(0) + _ids(1) + _ids(2) + _ids(3))


def test_reshaping_the_map_sends_printify_nothing(
    workspace_root: Path, product_ctx: RunContext
) -> None:
    lock = _apply_product(product_ctx, a_lock())

    edit_listing(workspace_root, design={"on-light": DESIGN, "on-dark": DESIGN})

    assert _product_plan(product_ctx, lock).will_run is False


def test_a_print_area_recorded_before_a35_needs_no_update(product_ctx: RunContext) -> None:
    """The first plan after upgrade. A lockfile written before A35 keyed each
    print area by its artwork name; the design hash and variant ids it holds
    are unchanged, so the product is left alone."""
    lock = _apply_product(product_ctx, a_lock())
    applied = lock.applied["printify_product"]
    old_shape = {
        **applied,
        "print_areas": [{"artwork": "default", **area} for area in applied["print_areas"]],
    }
    upgraded = lock.model_copy(update={"applied": {**lock.applied, "printify_product": old_shape}})

    assert _product_plan(product_ctx, upgraded).will_run is False


def test_an_unclassified_colour_blocks_the_product(
    workspace_root: Path, product_ctx: RunContext
) -> None:
    edit_garment_profile(
        workspace_root, PROFILE, colors={c: t for c, t in TONES.items() if c != "ivory"}
    )

    product_plan = _product_plan(product_ctx, a_lock())

    assert product_plan.blocked is not None
    assert "Ivory isn't marked light or dark" in product_plan.blocked


def test_the_print_area_file_is_the_one_each_colour_resolves_to(
    workspace_root: Path, product_ctx: RunContext, printify: FakePrintifyClient
) -> None:
    """A colour's own design reaches Printify: moss prints its own file."""
    moss = workspace_root / "designs" / "moss-special.png"
    moss.write_bytes((workspace_root / DESIGN).read_bytes() + b"\x00")
    edit_listing(workspace_root, design={"default": DESIGN, "moss": "designs/moss-special.png"})

    _apply_product(product_ctx, a_lock())

    [created] = printify.created
    areas = {
        area.placeholders[0].images[0].id: sorted(area.variant_ids) for area in created.print_areas
    }
    assert areas == {
        _upload_id(workspace_root / DESIGN): sorted(_ids(0) + _ids(1) + _ids(2)),
        _upload_id(moss): _ids(3),
    }

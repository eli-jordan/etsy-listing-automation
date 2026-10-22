"""The whole pipeline against in-memory clients, for a test that plans or
applies every stage rather than one.

:func:`a_deployable_context` edits the fixture workspace until every stage
can run -- a Printify shop, an Etsy shop and its defaults, concrete copy, a
design large enough for the print area, a pricing plan -- and hands back a
context whose fakes agree with it. :func:`real_stages` is ``STAGES`` with
``publish``'s poll unable to wait. A test that needs something more (a shared
image, a video) adds it to ``media:`` itself, so the call site shows what
the test is about.
"""

from __future__ import annotations

from pathlib import Path

from etsy_listings.core.clients.etsy.fakes import FakeEtsyListingClient
from etsy_listings.core.clients.etsy.models import ReturnPolicy, ShippingProfile
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ProductExternal,
    Shop,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.core.engine.context import RunContext
from etsy_listings.core.engine.stage import Stage
from etsy_listings.core.engine.stages import STAGES
from etsy_listings.core.engine.stages.publish import PublishStage

from tests.support.builders import (
    a_context,
    edit_garment_profile,
    edit_listing,
    set_copy,
    set_etsy_listing_defaults,
    set_etsy_shop_id,
    set_shop_id,
    write_design,
)

SHOP_ID = 28819281
ETSY_SHOP_ID = 12345678
ETSY_LISTING_ID = 4572550919
GARMENT_PROFILE = "comfort-colors-1717"
FULL_PRINT_AREA = (4500, 5400)
"""The fixture profile's own print area, as Printify reports it for this
garment. Only a test about resolution itself needs a design this size."""
PRINT_AREA = (450, 540)
"""A tenth of :data:`FULL_PRINT_AREA`, written into the profile, the catalog
placeholder and the design together (T05). A stage that prices, adopts or
diffs a product does not care how many pixels the art has, and a 4500x5400
RGBA design costs every such case a ~100 MB encode and hash. The resolution
gate still runs against the shrunken profile; nothing here bypasses it."""
PLAN = "pricing-plans/launch.yaml"
DESIGN = "designs/take-a-hike.png"
COLOURS = ["Black", "Blue Jean", "Ivory", "Moss"]
SIZES = ["S", "M", "L", "XL", "XXL", "XXXL"]


def variants(print_area: tuple[int, int] = PRINT_AREA) -> VariantSet:
    """Every colour in every size, ids ``1000 + colour * 10 + size``."""
    placeholder = PrintAreaPlaceholder(position="front", width=print_area[0], height=print_area[1])
    return VariantSet(
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


def a_catalog(print_area: tuple[int, int] = PRINT_AREA) -> FakeCatalogClient:
    """The fixture garment's blueprint 706 / provider 29, its front placeholder
    matching ``print_area``."""
    return FakeCatalogClient(
        blueprints=[
            Blueprint(
                id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
            )
        ],
        providers_by_blueprint={706: [PrintProvider(id=29, title="Monster Digital")]},
        variants_by_key={(706, 29): variants(print_area)},
    )


def at_print_area(root: Path, print_area: tuple[int, int] = PRINT_AREA) -> Path:
    """Set the fixture profile's print area and write a design exactly that
    size: the passing value of the resolution gate, at whatever scale."""
    edit_garment_profile(
        root, GARMENT_PROFILE, print_area={"width": print_area[0], "height": print_area[1]}
    )
    return write_design(root, print_area)


def a_deployable_context(root: Path) -> RunContext:
    set_shop_id(root, SHOP_ID)
    set_etsy_shop_id(root, ETSY_SHOP_ID)
    set_etsy_listing_defaults(root, shipping_profile="NOK standard tee")
    set_copy(root, title="Take A Hike Tee", description="A retro sunset.")
    at_print_area(root)
    (root / "pricing-plans").mkdir()
    (root / PLAN).write_text(
        "garment_profile: comfort-colors-1717\nprices:\n"
        + "".join(f"  {size}: 349 NOK\n" for size in SIZES),
        encoding="utf-8",
    )
    edit_listing(root, design=DESIGN, pricing_plan=PLAN, prices={})

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
    return a_context(root, catalog=a_catalog(), printify=printify, etsy=etsy)


def real_stages() -> list[Stage]:
    """The real pipeline, with `publish`'s poll unable to wait."""
    return [PublishStage(sleep=lambda seconds: None) if s.name == "publish" else s for s in STAGES]

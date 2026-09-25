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
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.stage import Stage
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.publish import PublishStage

from tests.support.builders import (
    a_context,
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
PRINT_AREA = (4500, 5400)
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


def a_deployable_context(root: Path) -> RunContext:
    set_shop_id(root, SHOP_ID)
    set_etsy_shop_id(root, ETSY_SHOP_ID)
    set_etsy_listing_defaults(root, shipping_profile="NOK standard tee")
    set_copy(root, title="Take A Hike Tee", description="A retro sunset.")
    write_design(root, PRINT_AREA)
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
    return a_context(root, catalog=_catalog(), printify=printify, etsy=etsy)


def real_stages() -> list[Stage]:
    """The real pipeline, with `publish`'s poll unable to wait."""
    return [PublishStage(sleep=lambda seconds: None) if s.name == "publish" else s for s in STAGES]

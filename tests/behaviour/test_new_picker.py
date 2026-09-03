"""Behaviour tests for the `new` picker's logic, through the fake catalog
client -- no live Printify catalog, no terminal, per the plan's guidance:
"drive it in tests through the fake catalog client and make sure the
interactive path is thin enough to be obviously correct.\""""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.config.slug import ColourExceptions, SlugCollisionError
from etsy_listings.newcmd.logic import (
    build_listing_stub,
    build_profile,
    filter_blueprints_by_category,
    profile_slug_for,
    resolve_colour_slugs,
    sort_sizes,
    validate_listing_stub,
    write_listing,
    write_profile_if_absent,
)
from etsy_listings.workspace.workspace import Workspace

TSHIRT = Blueprint(
    id=6, title="Unisex Garment-Dyed Heavy Weight Tee", brand="Comfort Colors", model="1717"
)
HOODIE = Blueprint(id=99, title="Unisex Pullover Hoodie", brand="Gildan", model="18500")
MUG = Blueprint(id=7, title="11oz Ceramic Mug", brand="Generic", model="MUG-11")

PROVIDER = PrintProvider(id=29, title="Monster Digital")

VARIANT_SET = VariantSet(
    variants=(
        Variant(id=1, title="Black / S", options=VariantOptions(color="Black", size="S")),
        Variant(id=2, title="Black / M", options=VariantOptions(color="Black", size="M")),
        Variant(id=3, title="Blue Jean / S", options=VariantOptions(color="Blue Jean", size="S")),
        Variant(id=4, title="Blue Jean / M", options=VariantOptions(color="Blue Jean", size="M")),
    ),
    placeholders=(PrintAreaPlaceholder(position="front", width=4500, height=5400),),
)


def test_filter_blueprints_by_category_matches_tshirt_keywords() -> None:
    result = filter_blueprints_by_category([TSHIRT, HOODIE, MUG], "tshirt")
    assert result == [TSHIRT]


def test_filter_blueprints_by_category_unknown_category_falls_back_to_literal_match() -> None:
    result = filter_blueprints_by_category([TSHIRT, MUG], "mug")
    assert result == [MUG]


def test_sort_sizes_orders_known_sizes_then_appends_unknown() -> None:
    assert sort_sizes({"L", "S", "M", "Custom"}) == ["S", "M", "L", "Custom"]


def test_resolve_colour_slugs_maps_printify_names_to_slugs() -> None:
    result = resolve_colour_slugs(VARIANT_SET, ColourExceptions(root={}))
    assert result == {"Black": "black", "Blue Jean": "blue-jean"}


def test_resolve_colour_slugs_raises_on_collision() -> None:
    collision_set = VariantSet(
        variants=(
            Variant(id=1, title="A", options=VariantOptions(color="Blue-Jean", size="S")),
            Variant(id=2, title="B", options=VariantOptions(color="Blue Jean", size="S")),
        ),
        placeholders=(),
    )
    with pytest.raises(SlugCollisionError):
        resolve_colour_slugs(collision_set, ColourExceptions(root={}))


def test_build_profile_reads_print_area_from_placeholder() -> None:
    profile = build_profile(
        blueprint_title=TSHIRT.title,
        provider_title=PROVIDER.title,
        placeholder="front",
        variant_set=VARIANT_SET,
    )
    assert profile.print_area.width == 4500
    assert profile.print_area.height == 5400
    assert profile.sizes == ["S", "M"]


def test_build_profile_raises_actionable_error_for_missing_placeholder() -> None:
    with pytest.raises(ValueError, match="back"):
        build_profile(
            blueprint_title=TSHIRT.title,
            provider_title=PROVIDER.title,
            placeholder="back",
            variant_set=VARIANT_SET,
        )


def test_profile_slug_for_matches_config_slug_rules() -> None:
    assert profile_slug_for(TSHIRT) == "unisex-garment-dyed-heavy-weight-tee"


def test_write_profile_if_absent_writes_once_then_reuses(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    profile = build_profile(
        blueprint_title=TSHIRT.title,
        provider_title=PROVIDER.title,
        placeholder="front",
        variant_set=VARIANT_SET,
    )
    slug = profile_slug_for(TSHIRT)

    first = write_profile_if_absent(workspace, slug, profile)
    second = write_profile_if_absent(workspace, slug, profile)

    assert first is True
    assert second is False
    assert (workspace.root / "profiles" / f"{slug}.yaml").is_file()


def test_build_listing_stub_has_one_price_per_size_and_one_mockup_per_colour() -> None:
    data = build_listing_stub(
        profile_slug="unisex-garment-dyed-heavy-weight-tee",
        design_ref="../../designs/take-a-hike.png",
        template="flat-lay-01",
        colours=["black", "blue-jean"],
        sizes=["S", "M"],
        base_price="0 NOK",
        brief="",
    )
    assert data["prices"] == {"S": "0 NOK", "M": "0 NOK"}
    assert data["media"] == [
        {"template": "flat-lay-01", "colour": "black"},
        {"template": "flat-lay-01", "colour": "blue-jean"},
    ]
    assert data["etsy"]["title"] == "<generate>"


def test_validate_listing_stub_rejects_currency_mismatch() -> None:
    data = build_listing_stub(
        profile_slug="p",
        design_ref="../../designs/x.png",
        template="flat-lay-01",
        colours=["black"],
        sizes=["S"],
        base_price="0 USD",
        brief="",
    )
    with pytest.raises(Exception, match="USD"):
        validate_listing_stub(data, currency="NOK")


def test_write_listing_refuses_to_overwrite_an_existing_listing(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    data = build_listing_stub(
        profile_slug="comfort-colors-1717",
        design_ref="../../designs/take-a-hike.png",
        template="flat-lay-01",
        colours=["black"],
        sizes=["S"],
        base_price="0 NOK",
        brief="",
    )
    with pytest.raises(FileExistsError):
        write_listing(workspace, "take-a-hike", data)  # fixture already has this listing

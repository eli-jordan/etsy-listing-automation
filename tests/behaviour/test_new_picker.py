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
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.listing import MAX_MEDIA_ENTRIES
from etsy_listings.config.slug import ColourExceptions, SlugCollisionError
from etsy_listings.newcmd.logic import (
    build_listing_stub,
    build_media_entries,
    build_profile,
    filter_blueprints_by_category,
    load_template_kind,
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

SMALL_FRONT = (PrintAreaPlaceholder(position="front", width=3461, height=3955),)
LARGE_FRONT = (PrintAreaPlaceholder(position="front", width=4500, height=5400),)
"""Placeholders hang off each *variant*, and differ by garment size -- which is
what the real payload does. See `Variant.placeholders`."""

VARIANT_SET = VariantSet(
    variants=(
        Variant(
            id=1,
            title="Black / S",
            options=VariantOptions(color="Black", size="S"),
            placeholders=SMALL_FRONT,
        ),
        Variant(
            id=2,
            title="Black / M",
            options=VariantOptions(color="Black", size="M"),
            placeholders=LARGE_FRONT,
        ),
        Variant(
            id=3,
            title="Blue Jean / S",
            options=VariantOptions(color="Blue Jean", size="S"),
            placeholders=SMALL_FRONT,
        ),
        Variant(
            id=4,
            title="Blue Jean / M",
            options=VariantOptions(color="Blue Jean", size="M"),
            placeholders=LARGE_FRONT,
        ),
    ),
)


def test_filter_blueprints_by_category_matches_tshirt_keywords() -> None:
    result = filter_blueprints_by_category([TSHIRT, HOODIE, MUG], "tshirt")
    assert result == [TSHIRT]


def test_filter_blueprints_by_category_unknown_category_falls_back_to_literal_match() -> None:
    result = filter_blueprints_by_category([TSHIRT, MUG], "mug")
    assert result == [MUG]


def test_sort_sizes_orders_known_sizes_then_appends_unknown() -> None:
    assert sort_sizes({"L", "S", "M", "Custom"}) == ["S", "M", "L", "Custom"]


def test_sort_sizes_knows_printifys_numeric_spelling_of_the_big_sizes() -> None:
    """The real catalog sends `2XL`/`3XL`, not `XXL`/`XXXL`. With only the
    lettered spellings known, they sorted into the alphabetical unknown tail
    while `4XL` sorted normally -- so a real profile came out `S M L XL 4XL
    2XL 3XL`."""
    assert sort_sizes({"S", "M", "L", "XL", "2XL", "3XL", "4XL"}) == [
        "S",
        "M",
        "L",
        "XL",
        "2XL",
        "3XL",
        "4XL",
    ]


def test_sort_sizes_still_handles_the_lettered_spelling() -> None:
    assert sort_sizes({"XXXL", "S", "XXL"}) == ["S", "XXL", "XXXL"]


def test_resolve_colour_slugs_maps_printify_names_to_slugs() -> None:
    result = resolve_colour_slugs(VARIANT_SET, ColourExceptions(root={}))
    assert result == {"Black": "black", "Blue Jean": "blue-jean"}


def test_resolve_colour_slugs_raises_on_collision() -> None:
    collision_set = VariantSet(
        variants=(
            Variant(id=1, title="A", options=VariantOptions(color="Blue-Jean", size="S")),
            Variant(id=2, title="B", options=VariantOptions(color="Blue Jean", size="S")),
        ),
    )
    with pytest.raises(SlugCollisionError):
        resolve_colour_slugs(collision_set, ColourExceptions(root={}))


def test_build_profile_reads_print_area_from_the_largest_placeholder() -> None:
    """One profile, one print area (PRD 8a), but the catalog offers one per
    garment size -- the largest wins, so the design is sized for the panel
    that needs the most pixels."""
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
        colours=["black", "blue-jean"],
        sizes=["S", "M"],
        base_price="0 NOK",
        brief="",
        media=build_media_entries(
            template="flat-lay-01", kind="colour-matrix", colours=["black", "blue-jean"]
        ),
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
        colours=["black"],
        sizes=["S"],
        base_price="0 USD",
        brief="",
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )
    with pytest.raises(Exception, match="USD"):
        validate_listing_stub(data, currency="NOK")


# --- what goes in `media:` ---------------------------------------------------
#
# Two things constrain it, and `new` got both wrong. Etsy accepts at most 10
# images while a print provider can offer far more colours (Comfort Colors
# 1717 / Monster Digital: 33), and the shape of a valid entry depends on the
# referenced template's kind (A11) -- a `single` template has one output and
# no colour to name.


def test_a_colour_matrix_template_gets_one_media_entry_per_colour() -> None:
    media = build_media_entries(
        template="flat-lay-01", kind="colour-matrix", colours=["black", "ivory"]
    )
    assert media == [
        {"template": "flat-lay-01", "colour": "black"},
        {"template": "flat-lay-01", "colour": "ivory"},
    ]


def test_media_stops_at_etsys_ten_image_limit() -> None:
    """33 colours produced 33 media entries and a listing that would not
    validate -- the failure `new` hit on a real Printify provider."""
    colours = [f"colour-{n:02d}" for n in range(33)]
    media = build_media_entries(template="flat-lay-01", kind="colour-matrix", colours=colours)

    assert len(media) == MAX_MEDIA_ENTRIES
    assert [entry["colour"] for entry in media] == colours[:MAX_MEDIA_ENTRIES]


def test_a_truncated_stub_still_validates_and_still_sells_every_colour() -> None:
    """The cap belongs to `media`, not to `colors`: colours decide which
    Printify variants sell, photos are a separate axis (PRD 31)."""
    colours = [f"colour-{n:02d}" for n in range(33)]
    data = build_listing_stub(
        profile_slug="p",
        design_ref="../../designs/x.png",
        colours=colours,
        sizes=["S"],
        base_price="0 NOK",
        brief="",
        media=build_media_entries(template="flat-lay-01", kind="colour-matrix", colours=colours),
    )

    listing = validate_listing_stub(data, currency="NOK")
    assert len(listing.colors) == 33
    assert len(listing.media) == MAX_MEDIA_ENTRIES


@pytest.mark.parametrize("kind", ["multiple", "single"])
def test_a_single_or_multiple_template_gets_one_entry_and_no_colour(kind: str) -> None:
    """One output each, so there is nothing to disambiguate (PRD 28) -- and a
    `colour` on such an entry is rejected downstream, which is exactly the
    listing `new` used to write."""
    media = build_media_entries(
        template="dancing-guy-in-red", kind=kind, colours=["black", "ivory"]
    )
    assert media == [{"template": "dancing-guy-in-red"}]


def test_load_template_kind_reads_the_templates_own_file(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    assert load_template_kind(workspace, "flat-lay-01") == "colour-matrix"
    assert load_template_kind(workspace, "colour-chart-01") == "multiple"


def test_load_template_kind_names_an_uncalibrated_template(workspace_root: Path) -> None:
    (workspace_root / "mockup-templates" / "half-built").mkdir()
    workspace = Workspace.discover(root_override=workspace_root)
    with pytest.raises(ConfigLoadError, match="template config not found"):
        load_template_kind(workspace, "half-built")


def test_template_names_lists_only_calibrated_templates(workspace_root: Path) -> None:
    """A directory without a template.yaml has no kind and no geometry, so
    offering it in the picker would only move the failure later."""
    (workspace_root / "mockup-templates" / "half-built").mkdir()
    workspace = Workspace.discover(root_override=workspace_root)
    assert workspace.template_names() == ["colour-chart-01", "flat-lay-01"]


def test_template_names_is_empty_without_a_templates_directory(tmp_path: Path) -> None:
    (tmp_path / "shop.yaml").write_text(
        "etsy:\n  shop_id: 1\n  who_made: i_did\n  when_made: made_to_order\n"
        "  is_supply: false\ncurrency: NOK\n",
        encoding="utf-8",
    )
    assert Workspace.discover(root_override=tmp_path).template_names() == []


def test_write_listing_refuses_to_overwrite_an_existing_listing(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    data = build_listing_stub(
        profile_slug="comfort-colors-1717",
        design_ref="../../designs/take-a-hike.png",
        colours=["black"],
        sizes=["S"],
        base_price="0 NOK",
        brief="",
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )
    with pytest.raises(FileExistsError):
        write_listing(workspace, "take-a-hike", data)  # fixture already has this listing

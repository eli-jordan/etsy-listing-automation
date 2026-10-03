"""Garment profiles from a Printify catalog entry, called directly: which
blueprints a category means, the size order, colour slugs, the print area,
the profile's slug and when it is written, and which garments a workspace
already uses. Moved from the `new` picker's tests (test-suite quality plan,
PR 9); the picker rows built from these stay in
``tests/cli/behaviour/test_new_picker.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application.garment_profiles import (
    build_garment_profile,
    filter_blueprints_by_category,
    garment_profile_slug_for,
    local_blueprint_keys,
    resolve_colour_slugs,
    sort_sizes,
    write_garment_profile_if_absent,
)
from etsy_listings.core.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.core.config.slug import ColourExceptions, SlugCollisionError
from etsy_listings.core.workspace.workspace import Workspace

MUG = Blueprint(id=7, title="11oz Ceramic Mug", brand="Generic", model="MUG-11")
TSHIRT = Blueprint(
    id=6, title="Unisex Garment-Dyed Heavy Weight Tee", brand="Comfort Colors", model="1717"
)
HOODIE = Blueprint(id=99, title="Unisex Pullover Hoodie", brand="Gildan", model="18500")
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
    while `4XL` sorted normally -- so a real garment profile came out `S M L XL 4XL
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


def test_build_garment_profile_reads_print_area_from_the_largest_placeholder() -> None:
    """One garment profile, one print area, but the catalog offers
    one per garment size -- the largest wins, so the design is sized for the
    panel that needs the most pixels."""
    profile = build_garment_profile(
        blueprint=TSHIRT,
        provider_title=PROVIDER.title,
        placeholder="front",
        variant_set=VARIANT_SET,
    )
    assert profile.print_area.width == 4500
    assert profile.print_area.height == 5400
    assert profile.sizes == ["S", "M"]


def test_build_garment_profile_raises_actionable_error_for_missing_placeholder() -> None:
    with pytest.raises(ValueError, match="back"):
        build_garment_profile(
            blueprint=TSHIRT,
            provider_title=PROVIDER.title,
            placeholder="back",
            variant_set=VARIANT_SET,
        )


def test_garment_profile_slug_for_is_brand_and_model_not_the_title() -> None:
    """ADR-0005. A title slug would file every brand's version of the same shirt
    under one name -- Printify calls the Comfort Colors 1717 "Unisex
    Garment-Dyed T-shirt", and so do several other brands' entries."""
    assert garment_profile_slug_for(TSHIRT) == "comfort-colors-1717"


def test_garment_profile_slug_drops_the_trademark_sign() -> None:
    """The catalog's brand really is "Comfort Colors®"; a filename with a ® in
    it is not one anyone wants to type at a shell."""
    catalog_entry = Blueprint(
        id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
    )
    assert garment_profile_slug_for(catalog_entry) == "comfort-colors-1717"


def test_write_garment_profile_if_absent_writes_once_then_reuses(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    profile = build_garment_profile(
        blueprint=HOODIE,
        provider_title=PROVIDER.title,
        placeholder="front",
        variant_set=VARIANT_SET,
    )
    slug = garment_profile_slug_for(HOODIE)  # gildan-18500: not in the fixture workspace

    first = write_garment_profile_if_absent(workspace, slug, profile)
    second = write_garment_profile_if_absent(workspace, slug, profile)

    assert first is True
    assert second is False
    assert (workspace.root / "garment-profiles" / f"{slug}.yaml").is_file()


def test_an_existing_garment_profile_for_the_same_garment_is_reused_untouched(
    workspace_root: Path,
) -> None:
    """`new` writes garment-profiles/{slug}.yaml if absent; reuses it
    silently if present. Since the slug is brand+model, a second listing on
    the garment the workspace already has a garment profile for finds it --
    which is the whole point of the garment profile being shared. The
    fixture's Comfort Colors 1717 is that case."""
    workspace = Workspace.discover(root_override=workspace_root)
    existing = workspace.garment_profile_file(garment_profile_slug_for(TSHIRT))
    assert existing.is_file(), "fixture should already hold this garment's profile"
    before = existing.read_bytes()

    profile = build_garment_profile(
        blueprint=TSHIRT,
        provider_title=PROVIDER.title,
        placeholder="front",
        variant_set=VARIANT_SET,
    )
    slug = garment_profile_slug_for(TSHIRT)
    assert write_garment_profile_if_absent(workspace, slug, profile) is False
    assert existing.read_bytes() == before, "an existing garment profile must not be rewritten"


def test_local_blueprint_keys_reads_the_workspace_garment_profiles(workspace_root: Path) -> None:
    """The fixture workspace holds one garment profile, `comfort-colors-1717`,
    whose `blueprint:` says `brand: Comfort Colors` / `model: "1717"`.

    Written out as a literal. Deriving the expected set the way the code does
    -- `normalise(profile.blueprint.brand)` over `garment_profile_names()` --
    passes for *any* behaviour `normalise` might have, including none: both
    sides move together, so the assertion can never disagree with the
    implementation. The casefolding it is really claiming is only visible
    when one side is fixed.
    """
    workspace = Workspace.discover(root_override=workspace_root)

    assert local_blueprint_keys(workspace) == {("comfort colors", "1717")}


def test_a_broken_garment_profile_costs_a_marker_not_the_whole_picker(
    workspace_root: Path,
) -> None:
    (workspace_root / "garment-profiles" / "broken.yaml").write_text(
        "not: a garment profile\n", encoding="utf-8"
    )
    workspace = Workspace.discover(root_override=workspace_root)
    assert local_blueprint_keys(workspace)  # the valid ones still resolve


def test_a_workspace_with_no_garment_profiles_directory_has_no_local_keys(
    tmp_path: Path,
) -> None:
    (tmp_path / "shop.yaml").write_text(
        "etsy:\n  shop_id: 1\n  currency: NOK\n",
        encoding="utf-8",
    )
    workspace = Workspace.discover(root_override=tmp_path)
    assert workspace.garment_profile_names() == []
    assert local_blueprint_keys(workspace) == set()

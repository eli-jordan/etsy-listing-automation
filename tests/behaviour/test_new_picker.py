"""Behaviour tests for the `new` picker's logic, through the fake catalog
client -- no live Printify catalog, no terminal, per the plan's guidance:
"drive it in tests through the fake catalog client and make sure the
interactive path is thin enough to be obviously correct.\""""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from etsy_listings.clients.printify.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingCost,
    ShippingProfile,
    ShippingRates,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.clients.printify.resolve import normalise
from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.listing import MAX_MEDIA_ENTRIES
from etsy_listings.config.money import Money
from etsy_listings.config.pricing_plan import PricingPlan
from etsy_listings.config.slug import ColourExceptions, SlugCollisionError
from etsy_listings.newcmd.fx_rate import FxRate
from etsy_listings.newcmd.logic import (
    build_blueprint_choices,
    build_design_choices,
    build_garment_profile,
    build_listing_stub,
    build_media_entries,
    build_pricing_plan_choices,
    compute_starting_prices,
    filter_blueprints_by_category,
    garment_profile_slug_for,
    load_candidate_pricing_plans,
    load_template_kind,
    local_blueprint_keys,
    pricing_plan_ref,
    resolve_colour_slugs,
    sort_sizes,
    validate_listing_stub,
    write_garment_profile_if_absent,
    write_listing,
    write_pricing_plan,
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
    """One garment profile, one print area (PRD 8a), but the catalog offers
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
    """PRD 23. A title slug would file every brand's version of the same shirt
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
    """PRD: `new` "writes garment-profiles/{slug}.yaml if absent; reuses it
    silently if present". Since the slug is brand+model, a second listing on
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


def test_build_listing_stub_references_a_pricing_plan_and_leaves_prices_empty() -> None:
    data = build_listing_stub(
        garment_profile_slug="unisex-garment-dyed-heavy-weight-tee",
        design_ref="../../designs/take-a-hike.png",
        colours=["black", "blue-jean"],
        pricing_plan_ref="../../pricing-plans/launch-low.yaml",
        brief="",
        media=build_media_entries(
            template="flat-lay-01", kind="colour-matrix", colours=["black", "blue-jean"]
        ),
    )
    assert data["pricing_plan"] == "../../pricing-plans/launch-low.yaml"
    assert data["prices"] == {}
    assert data["media"] == [
        {"template": "flat-lay-01", "colour": "black"},
        {"template": "flat-lay-01", "colour": "blue-jean"},
    ]
    assert data["etsy"]["title"] == ""
    assert data["etsy"]["description"] == {}
    assert data["etsy"]["tags"] == []


def test_validate_listing_stub_accepts_a_pricing_plan_reference_with_no_prices() -> None:
    data = build_listing_stub(
        garment_profile_slug="p",
        design_ref="../../designs/x.png",
        colours=["black"],
        pricing_plan_ref="../../pricing-plans/x.yaml",
        brief="",
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )
    listing = validate_listing_stub(data, currency="NOK")
    assert listing.pricing_plan == "../../pricing-plans/x.yaml"
    assert listing.prices == {}


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


def test_media_stops_at_etsys_image_limit() -> None:
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
        garment_profile_slug="p",
        design_ref="../../designs/x.png",
        colours=colours,
        pricing_plan_ref="../../pricing-plans/x.yaml",
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
        "etsy:\n  shop_id: 1\n  currency: NOK\n",
        encoding="utf-8",
    )
    assert Workspace.discover(root_override=tmp_path).template_names() == []


def test_write_listing_refuses_to_overwrite_an_existing_listing(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    data = build_listing_stub(
        garment_profile_slug="comfort-colors-1717",
        design_ref="../../designs/take-a-hike.png",
        colours=["black"],
        pricing_plan_ref="../../pricing-plans/x.yaml",
        brief="",
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )
    with pytest.raises(FileExistsError):
        write_listing(workspace, "take-a-hike", data)  # fixture already has this listing


# --- pricing plans (PRD 33-36) -----------------------------------------------


def test_build_pricing_plan_choices_marks_the_exact_profile_match(tmp_path: Path) -> None:
    matching = PricingPlan(
        garment_profile="comfort-colors-1717", prices={"S": Money.parse("100 NOK")}
    )
    other = PricingPlan(garment_profile="a-different-profile", prices={"S": Money.parse("100 NOK")})
    plans = [(tmp_path / "b-other.yaml", other), (tmp_path / "a-matching.yaml", matching)]

    choices = build_pricing_plan_choices(plans, "comfort-colors-1717")

    assert [c.marked for c in choices] == [True, False]
    assert choices[0].value.stem == "a-matching"
    assert choices[0].label.strip().endswith("a-matching")
    assert choices[1].label.startswith("  ")  # no marker for the non-matching row


def test_load_candidate_pricing_plans_skips_a_broken_plan_not_the_whole_picker(
    workspace_root: Path,
) -> None:
    plans_dir = workspace_root / "pricing-plans"
    plans_dir.mkdir()
    (plans_dir / "good.yaml").write_text(
        "garment_profile: comfort-colors-1717\nprices:\n  S: 100 NOK\n", encoding="utf-8"
    )
    (plans_dir / "bad.yaml").write_text("garment_profile: x\nprices:\n  S: 100\n", encoding="utf-8")

    workspace = Workspace.discover(root_override=workspace_root)
    candidates = load_candidate_pricing_plans(workspace)

    assert [path.stem for path, _ in candidates] == ["good"]


def test_pricing_plan_ref_is_relative_to_the_listing_directory(tmp_path: Path) -> None:
    listing_dir = tmp_path / "listings" / "take-a-hike"
    listing_dir.mkdir(parents=True)

    flat = tmp_path / "pricing-plans" / "launch-low.yaml"
    assert pricing_plan_ref(flat, listing_dir=listing_dir) == "../../pricing-plans/launch-low.yaml"

    nested = tmp_path / "pricing-plans" / "comfort-colors-1717" / "launch-low.yaml"
    assert (
        pricing_plan_ref(nested, listing_dir=listing_dir)
        == "../../pricing-plans/comfort-colors-1717/launch-low.yaml"
    )


def test_write_pricing_plan_sets_profile_from_the_chosen_garment_profile(
    workspace_root: Path,
) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    prices = {"S": Money.parse("100 NOK")}

    path = write_pricing_plan(workspace, "Launch Low", "comfort-colors-1717", prices, ["a note"])

    assert path == workspace.pricing_plans_dir() / "launch-low.yaml"
    plan = workspace.load_pricing_plan(path)
    assert plan.garment_profile == "comfort-colors-1717"
    assert plan.prices == prices
    assert "a note" in path.read_text(encoding="utf-8")


def test_write_pricing_plan_refuses_to_overwrite(workspace_root: Path) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    prices = {"S": Money.parse("100 NOK")}
    write_pricing_plan(workspace, "dup", "comfort-colors-1717", prices, [])
    with pytest.raises(FileExistsError):
        write_pricing_plan(workspace, "dup", "comfort-colors-1717", prices, [])


def _shipping_rates(*, small_cents: int, medium_cents: int) -> ShippingRates:
    return ShippingRates(
        profiles=(
            ShippingProfile(
                variant_ids=(1, 3),
                first_item=ShippingCost(currency="USD", cost=small_cents),
                additional_items=ShippingCost(currency="USD", cost=small_cents),
            ),
            ShippingProfile(
                variant_ids=(2, 4),
                first_item=ShippingCost(currency="USD", cost=medium_cents),
                additional_items=ShippingCost(currency="USD", cost=medium_cents),
            ),
        )
    )


def test_compute_starting_prices_applies_margin_and_converts_currency() -> None:
    # variants 1 (Black/S) and 3 (Blue Jean/S) both cost 1000c mfg + 500c shipping.
    variant_costs = {1: 1000, 2: 1500, 3: 1000, 4: 1500}
    shipping = _shipping_rates(small_cents=500, medium_cents=600)
    rate = FxRate(rate=Decimal("10"), source="test", fetched_at=datetime.now(UTC))

    prices, notes = compute_starting_prices(
        sizes=["S", "M"],
        variant_set=VARIANT_SET,
        variant_costs=variant_costs,
        shipping=shipping,
        fx_rate=rate,
        target_currency="NOK",
    )

    # S: (10.00 + 5.00) * 1.10 = 16.50 USD * 10 = 165.00 NOK
    assert prices["S"] == Money.parse("165.00 NOK")
    # M: (15.00 + 6.00) * 1.10 = 23.10 USD * 10 = 231.00 NOK
    assert prices["M"] == Money.parse("231.00 NOK")
    assert any("S" in note for note in notes)


def test_compute_starting_prices_uses_the_max_when_colours_disagree() -> None:
    # Both size-S variants (1 and 3) get different manufacturing costs.
    variant_costs = {1: 1000, 3: 2000}
    shipping = _shipping_rates(small_cents=0, medium_cents=0)
    rate = FxRate(rate=Decimal("1"), source="test", fetched_at=datetime.now(UTC))

    prices, notes = compute_starting_prices(
        sizes=["S"],
        variant_set=VARIANT_SET,
        variant_costs=variant_costs,
        shipping=shipping,
        fx_rate=rate,
        target_currency="USD",
    )

    # max(1000, 2000) = 2000c = $20.00, * 1.10 margin = $22.00
    assert prices["S"] == Money.parse("22.00 USD")
    assert any("varies by colour" in note for note in notes)


def test_compute_starting_prices_is_fail_soft_with_no_cost_data() -> None:
    shipping = _shipping_rates(small_cents=500, medium_cents=600)

    prices, notes = compute_starting_prices(
        sizes=["S"],
        variant_set=VARIANT_SET,
        variant_costs={},  # the undocumented endpoint returned nothing
        shipping=shipping,
        fx_rate=FxRate(rate=Decimal("10"), source="test", fetched_at=datetime.now(UTC)),
        target_currency="NOK",
    )

    assert prices["S"] == Money.parse("0 NOK")
    assert any("no cost data" in note for note in notes)


def test_compute_starting_prices_is_fail_soft_with_no_fx_rate() -> None:
    variant_costs = {1: 1000, 3: 1000}
    shipping = _shipping_rates(small_cents=500, medium_cents=600)

    prices, notes = compute_starting_prices(
        sizes=["S"],
        variant_set=VARIANT_SET,
        variant_costs=variant_costs,
        shipping=shipping,
        fx_rate=None,  # the FX fetch failed
        target_currency="NOK",
    )

    assert prices["S"] == Money.parse("0 NOK")
    assert any("no FX rate" in note for note in notes)


# ----------------------------------------------------------------------
# The design picker: newest artwork first, since a design is usually made
# minutes before the listing that ships it.
# ----------------------------------------------------------------------


def _design(workspace_root: Path, name: str, *, mtime: float) -> Path:
    path = workspace_root / "designs" / f"{name}.png"
    path.write_bytes(b"")
    os.utime(path, (mtime, mtime))
    return path


def test_design_choices_put_the_newest_design_first(workspace_root: Path) -> None:
    base = datetime(2026, 3, 1, 9, 0, tzinfo=UTC).timestamp()
    _design(workspace_root, "oldest", mtime=base)
    _design(workspace_root, "newest", mtime=base + 7200)
    _design(workspace_root, "middle", mtime=base + 3600)
    workspace = Workspace.discover(root_override=workspace_root)

    choices = build_design_choices(workspace.design_files(), set())

    # take-a-hike is the fixture's own design, checked out just now, so it
    # sorts above every backdated one.
    assert [c.value.stem for c in choices][-3:] == ["newest", "middle", "oldest"]


def test_design_choices_break_ties_on_name(workspace_root: Path) -> None:
    same = datetime(2026, 3, 1, 9, 0, tzinfo=UTC).timestamp()
    for name in ("beta", "alpha", "gamma"):
        _design(workspace_root, name, mtime=same)
    workspace = Workspace.discover(root_override=workspace_root)

    choices = build_design_choices(workspace.design_files(), set())

    assert [c.value.stem for c in choices if c.value.stem != "take-a-hike"] == [
        "alpha",
        "beta",
        "gamma",
    ]


def test_design_rows_carry_the_date_and_mark_designs_that_already_have_a_listing(
    workspace_root: Path,
) -> None:
    _design(workspace_root, "fresh", mtime=datetime(2026, 3, 1, 9, 30).timestamp())
    workspace = Workspace.discover(root_override=workspace_root)

    rows = {
        c.value.stem: c for c in build_design_choices(workspace.design_files(), {"take-a-hike"})
    }

    assert rows["fresh"].label == "2026-03-01 09:30  fresh"
    assert not rows["fresh"].marked
    assert rows["take-a-hike"].marked
    assert rows["take-a-hike"].label.endswith("  take-a-hike  (listing exists)")


def test_design_files_lists_only_flat_pngs(workspace_root: Path) -> None:
    (workspace_root / "designs" / "notes.txt").write_text("not artwork", encoding="utf-8")
    nested = workspace_root / "designs" / "archive"
    nested.mkdir()
    (nested / "old.png").write_bytes(b"")
    workspace = Workspace.discover(root_override=workspace_root)

    assert [p.name for p in workspace.design_files()] == ["take-a-hike.png"]


def test_design_files_is_empty_without_a_designs_directory(tmp_path: Path) -> None:
    (tmp_path / "shop.yaml").write_text(
        "etsy:\n  shop_id: 1\n  currency: NOK\n",
        encoding="utf-8",
    )
    assert Workspace.discover(root_override=tmp_path).design_files() == []


# --- the garment rows, and which count as "already used here" ----------------
#
# Moved here from the prompts file, where they sat because the marker glyph is
# printed by a picker. They are about `newcmd.logic`, which is what this file
# tests; the glyph is `terminal`'s, tested in tests/unit/test_terminal.py.

COMFORT_TEE = Blueprint(
    id=6, title="Unisex Garment-Dyed Heavy Weight Tee", brand="Comfort Colors", model="1717"
)
GILDAN_TEE = Blueprint(id=12, title="Unisex Heavy Cotton Tee", brand="Gildan", model="5000")
GILDAN_HOODIE = Blueprint(id=99, title="Unisex Pullover Hoodie", brand="Gildan", model="18500")
GILDAN_LONG = Blueprint(id=13, title="Unisex Long Sleeve Tee", brand="Gildan", model="2400")
ALL = [COMFORT_TEE, GILDAN_HOODIE, GILDAN_TEE, GILDAN_LONG]


def _key(blueprint: Blueprint) -> tuple[str, str]:
    """A blueprint as `local_blueprint_keys` reports it: normalised brand+model."""
    return (normalise(blueprint.brand), normalise(blueprint.model))


def test_locally_used_garments_come_first_and_carry_the_marker() -> None:
    choices = build_blueprint_choices(ALL, {_key(GILDAN_HOODIE)}, marker="* ")

    assert choices[0].value == GILDAN_HOODIE
    assert choices[0].marked is True
    assert choices[0].label.startswith("* ")
    assert all(not choice.marked for choice in choices[1:])


def test_rows_carry_brand_model_and_title_as_aligned_columns() -> None:
    """Brand and model, not an inferred garment type: "Gildan 18500" is what
    identifies a blank, and Printify supplies it rather than us guessing."""
    choices = build_blueprint_choices(ALL, set(), marker="* ")
    labels = [choice.label for choice in choices]

    for choice in choices:
        assert choice.value.brand in choice.label
        assert choice.value.model in choice.label
        assert choice.value.title in choice.label

    # Every row puts the title at the same column, which is what makes the
    # list scannable rather than ragged.
    title_columns = {label.index(c.value.title) for label, c in zip(labels, choices, strict=True)}
    assert len(title_columns) == 1


def test_the_model_column_sits_between_the_brand_and_the_title() -> None:
    label = build_blueprint_choices([GILDAN_HOODIE], set(), marker="* ")[0].label
    assert label.index("Gildan") < label.index("18500") < label.index("Unisex Pullover Hoodie")


def test_rows_without_a_local_profile_still_reserve_the_marker_column() -> None:
    choices = build_blueprint_choices(ALL, {_key(GILDAN_HOODIE)}, marker="* ")
    marked, unmarked = choices[0], choices[1]
    assert marked.label.index(marked.value.brand) == unmarked.label.index(unmarked.value.brand)


def test_within_a_group_rows_sort_by_brand_then_title() -> None:
    choices = build_blueprint_choices(ALL, set(), marker="* ")
    assert [(c.value.brand, c.value.title) for c in choices] == [
        ("Comfort Colors", "Unisex Garment-Dyed Heavy Weight Tee"),
        ("Gildan", "Unisex Heavy Cotton Tee"),
        ("Gildan", "Unisex Long Sleeve Tee"),
        ("Gildan", "Unisex Pullover Hoodie"),
    ]


def test_no_blueprints_produces_no_rows() -> None:
    assert build_blueprint_choices([], set()) == []


# --- which garments count as "already used here" -----------------------------


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


def test_a_local_key_ignores_case_and_the_trademark_sign(workspace_root: Path) -> None:
    """The catalog says "Comfort Colors®"; a hand-written garment profile says
    "Comfort Colors". The marker has to survive that, or the garment you used
    yesterday stops sorting to the top for a reason nobody can see."""
    workspace = Workspace.discover(root_override=workspace_root)
    catalog_entry = Blueprint(
        id=706, title="Unisex Garment-Dyed T-shirt", brand="Comfort Colors®", model="1717"
    )
    choices = build_blueprint_choices([catalog_entry], local_blueprint_keys(workspace))
    assert choices[0].marked is True


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

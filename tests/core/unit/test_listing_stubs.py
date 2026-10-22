"""The listing stub ``new`` writes, called directly: what it references,
that it validates with no prices, and which ``media:`` entries a template's
kind earns. Moved from the `new` picker's tests (test-suite quality plan,
PR 9); ``create_listing`` itself is
``tests/core/behaviour/test_listing_creation.py``'s."""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application.listing_creation import (
    build_listing_stub,
    build_media_entries,
    load_template_kind,
    validate_listing_stub,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.media import MAX_IMAGES
from etsy_listings.core.workspace.workspace import Workspace


def test_build_listing_stub_references_a_pricing_plan_and_leaves_prices_empty() -> None:
    data = build_listing_stub(
        garment_profile_slug="unisex-garment-dyed-heavy-weight-tee",
        design_ref="designs/take-a-hike.png",
        colours=["black", "blue-jean"],
        pricing_plan_ref="pricing-plans/launch-low.yaml",
        brief="",
        media=build_media_entries(
            template="flat-lay-01", kind="colour-matrix", colours=["black", "blue-jean"]
        ),
    )
    assert data["pricing_plan"] == "pricing-plans/launch-low.yaml"
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
        design_ref="designs/x.png",
        colours=["black"],
        pricing_plan_ref="pricing-plans/x.yaml",
        brief="",
        media=[{"template": "flat-lay-01", "colour": "black"}],
    )
    listing = validate_listing_stub(data, currency="NOK")
    assert listing.pricing_plan == "pricing-plans/x.yaml"
    assert listing.prices == {}


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

    assert len(media) == MAX_IMAGES
    assert [entry["colour"] for entry in media] == colours[:MAX_IMAGES]


def test_a_truncated_stub_still_validates_and_still_sells_every_colour() -> None:
    """The cap belongs to `media`, not to `colors`: colours decide which
    Printify variants sell, photos are a separate axis."""
    colours = [f"colour-{n:02d}" for n in range(33)]
    data = build_listing_stub(
        garment_profile_slug="p",
        design_ref="designs/x.png",
        colours=colours,
        pricing_plan_ref="pricing-plans/x.yaml",
        brief="",
        media=build_media_entries(template="flat-lay-01", kind="colour-matrix", colours=colours),
    )

    listing = validate_listing_stub(data, currency="NOK")
    assert len(listing.colors) == 33
    assert len(listing.media) == MAX_IMAGES


@pytest.mark.parametrize("kind", ["multiple", "single"])
def test_a_single_or_multiple_template_gets_one_entry_and_no_colour(kind: str) -> None:
    """One output each, so there is nothing to disambiguate -- and a
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

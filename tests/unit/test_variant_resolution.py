"""Colour slug × size → the integer variant ids Printify sells by.

The join every product write depends on. A listing names colours by slug
(PRD 7a) and a profile names sizes; Printify knows neither, only a flat list of
variants whose ``options`` carry its own colour *names*.

The interesting case is the one PRD 46 settles: Printify discontinues
individual cells -- ``Berry / 4XL`` exists on the blueprint and no longer in
the catalog -- and a listing offering six sizes in that colour is not wrong,
it is asking for something the printer stopped making. That is reported and
skipped. A colour with no variants at all is a different thing entirely: a
typo, and fatal.
"""

from __future__ import annotations

import pytest

from etsy_listings.clients.printify.models import Variant, VariantOptions, VariantSet
from etsy_listings.clients.printify.resolve import (
    CatalogResolutionError,
    UnknownSizeError,
    resolve_variants,
)
from etsy_listings.config.slug import ColourExceptions


def _variant(id: int, colour: str, size: str) -> Variant:
    return Variant(
        id=id, title=f"{colour} / {size}", options=VariantOptions(color=colour, size=size)
    )


FULL = VariantSet(
    variants=(
        _variant(1, "Black", "S"),
        _variant(2, "Black", "M"),
        _variant(3, "Black", "L"),
        _variant(4, "Blue Jean", "S"),
        _variant(5, "Blue Jean", "M"),
        _variant(6, "Blue Jean", "L"),
    )
)

NO_EXCEPTIONS = ColourExceptions()


def test_it_resolves_the_whole_matrix() -> None:
    resolution = resolve_variants(FULL, ["black", "blue-jean"], ["S", "M", "L"], NO_EXCEPTIONS)

    assert [v.id for v in resolution.variants] == [1, 2, 3, 4, 5, 6]
    assert resolution.missing == ()


def test_it_keeps_the_order_the_listing_asked_for() -> None:
    """Colours in listing order, sizes in profile order -- the payload reads
    like the config it came from, which is what makes a diff legible."""
    resolution = resolve_variants(FULL, ["blue-jean", "black"], ["L", "S"], NO_EXCEPTIONS)

    assert [(v.colour_slug, v.size) for v in resolution.variants] == [
        ("blue-jean", "L"),
        ("blue-jean", "S"),
        ("black", "L"),
        ("black", "S"),
    ]


def test_each_variant_carries_the_names_both_sides_use() -> None:
    """The slug for talking to the listing and the mockup files, Printify's
    own name for talking to Printify. Losing either means re-deriving it."""
    variant = resolve_variants(FULL, ["blue-jean"], ["S"], NO_EXCEPTIONS).variants[0]

    assert (variant.id, variant.colour, variant.colour_slug, variant.size) == (
        4,
        "Blue Jean",
        "blue-jean",
        "S",
    )


def test_a_cell_the_catalog_no_longer_offers_is_reported_not_fatal() -> None:
    """PRD 46. Printify dropped `Berry / 4XL`; the listing is not wrong for
    having asked, and refusing it would force the user to drop 4XL for every
    colour or drop the colour entirely."""
    partial = VariantSet(
        variants=(*FULL.variants, _variant(7, "Berry", "S"), _variant(8, "Berry", "M"))
    )

    resolution = resolve_variants(partial, ["black", "berry"], ["S", "M", "L"], NO_EXCEPTIONS)

    assert resolution.missing == (("berry", "L"),)
    assert [v.id for v in resolution.variants] == [1, 2, 3, 7, 8]


def test_a_colour_with_no_variants_at_all_is_fatal() -> None:
    """Not a discontinued cell -- a typo, and the error lists what it could
    have meant."""
    with pytest.raises(CatalogResolutionError) as exc_info:
        resolve_variants(FULL, ["blak"], ["S"], NO_EXCEPTIONS)

    message = str(exc_info.value)
    assert "blak" in message
    assert "black" in message and "blue-jean" in message


def test_a_size_no_colour_offers_is_fatal() -> None:
    """A cell missing from one colour is Printify's business; a size missing
    from every colour is a profile naming a size this garment is not made in."""
    with pytest.raises(UnknownSizeError) as exc_info:
        resolve_variants(FULL, ["black"], ["S", "XXXXL"], NO_EXCEPTIONS)

    message = str(exc_info.value)
    assert "XXXXL" in message
    assert "S" in message and "L" in message


def test_slug_exceptions_are_honoured() -> None:
    """The sparse exceptions file is how a colour that will not slugify
    cleanly still resolves, and it must apply here too -- not only where the
    mockup filenames are matched."""
    awkward = VariantSet(variants=(_variant(9, "Blue / Green", "S"),))
    exceptions = ColourExceptions({"Blue / Green": "blue-green"})

    resolution = resolve_variants(awkward, ["blue-green"], ["S"], exceptions)

    assert resolution.variants[0].id == 9


def test_a_slug_collision_is_raised_rather_than_silently_picking_one() -> None:
    """Two Printify colours slugging to one name means the listing's `black`
    is ambiguous. `slug_map` already refuses; this just must not swallow it."""
    from etsy_listings.config.slug import SlugCollisionError

    colliding = VariantSet(variants=(_variant(1, "Blue Jean", "S"), _variant(2, "Blue-Jean", "S")))

    with pytest.raises(SlugCollisionError):
        resolve_variants(colliding, ["blue-jean"], ["S"], NO_EXCEPTIONS)


def test_variants_outside_the_requested_matrix_are_left_out() -> None:
    """The enabled subset is the product's real content (docs/api-findings.md).
    Everything else on the blueprint is Printify's business, not ours."""
    resolution = resolve_variants(FULL, ["black"], ["S"], NO_EXCEPTIONS)

    assert [v.id for v in resolution.variants] == [1]


def test_the_resolution_reports_the_ids_as_a_set_for_the_print_area() -> None:
    """`print_areas.variant_ids` wants ids and nothing else, and building that
    list at three call sites is how they drift apart."""
    resolution = resolve_variants(FULL, ["black", "blue-jean"], ["S"], NO_EXCEPTIONS)

    assert resolution.ids() == (1, 4)


def test_ids_can_be_narrowed_to_one_colour_for_split_artwork() -> None:
    """PRD 30's on-light/on-dark split partitions the variants across two
    print areas, which needs the ids for a subset of colours."""
    resolution = resolve_variants(FULL, ["black", "blue-jean"], ["S", "M"], NO_EXCEPTIONS)

    assert resolution.ids(colours={"blue-jean"}) == (4, 5)

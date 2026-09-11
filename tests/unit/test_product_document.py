"""The product stage's applied document: what it holds, and what it refuses.

Two things that used to be separate and are the same subject. The document was
a bare `dict` read back with string keys, and the garment-change gate was a
function in `gates` reading that dict a second way. Both are now about
`AppliedProduct`, so both are tested here.

The bytes matter as much as the fields: this document is what `canonical_hash`
hashes, so a change in what it dumps is a change in every listing's
`input_hash` -- and therefore a re-apply of every product in the workspace.
"""

from __future__ import annotations

from pathlib import Path

from etsy_listings.engine.lock import canonical_hash
from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.placement import ArtworkGroup
from etsy_listings.engine.stages.product_document import (
    AppliedProduct,
    PricedVariant,
    PrintifyProductDesired,
    check_garment_unchanged,
)

BLACK_S = PricedVariant(id=2, colour_slug="black", size="S", price=34900)
BLACK_M = PricedVariant(id=1, colour_slug="black", size="M", price=34900)
IVORY_S = PricedVariant(id=3, colour_slug="ivory", size="S", price=37900)


def _desired(*variants: PricedVariant, **overrides: object) -> PrintifyProductDesired:
    fields: dict[str, object] = {
        "title": "Take A Hike Tee",
        "description": "A retro sunset.",
        "blueprint_id": 706,
        "print_provider_id": 29,
        "position": "front",
        "variants": variants or (BLACK_M, BLACK_S),
        "groups": (
            ArtworkGroup(
                artwork="default",
                colours=("black", "ivory"),
                design=Path("design.png"),
                design_hash="sha256:abc",
            ),
        ),
        "currency": "NOK",
    }
    fields.update(overrides)
    return PrintifyProductDesired(**fields)  # type: ignore[arg-type]


# ------------------------------------------------------- what gets written


def test_the_document_does_not_depend_on_the_order_colours_were_resolved_in() -> None:
    """The catalog resolves colour-outer, size-inner, so the order a listing
    writes ``colors:`` in reaches every list in this document unless something
    stops it -- and this document is hashed.

    It was not stopped. ``print_areas[].variant_ids`` came out in resolution
    order, so reordering ``colors:`` in listing.yaml changed ``input_hash``
    and re-applied a product nothing about which had changed. Both lists are
    sorted now.
    """
    one = _desired(BLACK_M, BLACK_S, IVORY_S).applied()
    another = _desired(IVORY_S, BLACK_S, BLACK_M).applied()

    assert [v.id for v in one.variants] == [1, 2, 3]
    assert one.print_areas[0].variant_ids == [1, 2, 3]
    assert one == another


def test_the_print_areas_do_not_depend_on_the_order_the_colours_were_written_in() -> None:
    """The same rule, one level up -- and the level the first version missed.

    ``group_by_artwork`` deduplicates in first-seen order on purpose, so the
    print areas follow the order the listing wrote ``colors:`` in. That is
    right for the payload and wrong for a document that is compared and
    hashed: moving a colour to the top of ``colors:`` reordered this list and
    made an unchanged product look changed. The test above only ever had one
    group, so it could not see this.
    """
    on_light = ArtworkGroup(
        artwork="on-light", colours=("ivory",), design=Path("l.png"), design_hash="sha256:l"
    )
    on_dark = ArtworkGroup(
        artwork="on-dark", colours=("black",), design=Path("d.png"), design_hash="sha256:d"
    )

    one = _desired(groups=(on_light, on_dark)).applied()
    another = _desired(groups=(on_dark, on_light)).applied()

    assert [area.artwork for area in one.print_areas] == ["on-dark", "on-light"]
    assert one == another
    assert canonical_hash(one.model_dump(mode="json")) == canonical_hash(
        another.model_dump(mode="json")
    )


def test_the_document_hashes_the_same_as_the_dict_it_replaced() -> None:
    """The shape written to `state.lock.json`, pinned as a literal.

    Derived the way the code derives it, this test would pass for any shape at
    all -- including one that silently re-applies every product in every
    workspace on upgrade. So it is written out.
    """
    document = _desired(BLACK_M, BLACK_S).applied().model_dump(mode="json")

    assert document == {
        "title": "Take A Hike Tee",
        "description": "A retro sunset.",
        "blueprint_id": 706,
        "print_provider_id": 29,
        "position": "front",
        "variants": [{"id": 1, "price": 34900}, {"id": 2, "price": 34900}],
        "print_areas": [{"artwork": "default", "design_hash": "sha256:abc", "variant_ids": [1, 2]}],
    }


def test_a_document_round_trips_through_json_unchanged() -> None:
    """It goes to disk as JSON and comes back as one. A field that survived the
    dump and not the parse would show as a permanent diff."""
    wanted = _desired().applied()
    reparsed = AppliedProduct.model_validate(wanted.model_dump(mode="json"))

    assert reparsed == wanted
    assert canonical_hash(reparsed.model_dump(mode="json")) == canonical_hash(
        wanted.model_dump(mode="json")
    )


# ---------------------------------------------------- garment change (PRD 37)


APPLIED = _desired().applied()


def test_an_unchanged_garment_passes() -> None:
    assert check_garment_unchanged(APPLIED, blueprint_id=706, print_provider_id=29) is None


def test_no_previous_apply_passes() -> None:
    """Nothing to have changed from. The first `apply` creates the product."""
    assert check_garment_unchanged(None, blueprint_id=706, print_provider_id=29) is None


def _refusal(blocked: Blocked | None) -> str:
    assert blocked is not None
    return blocked.message


def test_a_changed_blueprint_is_refused() -> None:
    """Printify answers 200 to a blueprint change and does nothing -- the
    quietest failure in that API. The only automated alternative is
    delete-and-recreate, which discards the Etsy listing's reviews and
    favourites to save retyping a short file."""
    message = _refusal(check_garment_unchanged(APPLIED, blueprint_id=6, print_provider_id=29))

    assert "706" in message and "6" in message
    assert "new listing" in message


def test_a_changed_print_provider_is_refused() -> None:
    message = _refusal(check_garment_unchanged(APPLIED, blueprint_id=706, print_provider_id=99))

    assert "29" in message and "99" in message


def test_both_changing_at_once_names_both() -> None:
    message = _refusal(check_garment_unchanged(APPLIED, blueprint_id=6, print_provider_id=99))

    assert "blueprint" in message and "print provider" in message


# ------------------------------------------------------------ priced cells


def test_a_group_takes_only_the_variants_whose_colour_it_covers() -> None:
    """PRD 30's on-light/on-dark split: one product's variants partitioned
    across two print areas by colour. The group knows colours; only the stage
    knows which Printify ids those are."""
    desired = _desired(BLACK_M, BLACK_S, IVORY_S)
    dark_only = ArtworkGroup(
        artwork="on-dark",
        colours=("black",),
        design=Path("dark.png"),
        design_hash="sha256:dark",
    )

    assert desired.variant_ids(dark_only) == (1, 2)


def test_prices_keyed_by_id_are_derived_not_stored() -> None:
    """`prices` used to be a field, with `price_labels` beside it to carry back
    the colour and size it had discarded. One list of cells answers both."""
    desired = _desired(BLACK_M, IVORY_S)

    assert desired.prices == {1: 34900, 3: 37900}
    assert [(v.colour_slug, v.size) for v in desired.variants] == [("black", "M"), ("ivory", "S")]

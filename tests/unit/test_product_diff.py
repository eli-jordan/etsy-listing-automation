"""The product stage's three-way comparison, asked directly.

Every assertion here used to need a fixture workspace, two fake clients and a
`build_plan` call, because the comparison lived behind underscored names
inside the stage module. That is what a closed seam costs: the price maths --
minor units back into `Money`, with the listing's currency -- was reachable
only through a behaviour test, so it was checked for its *type* and never for
its numbers.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from etsy_listings.clients.printify.models import Product, ProductVariant
from etsy_listings.config.money import Money
from etsy_listings.engine.change import Drift, FieldChange, ListChange, PriceChange
from etsy_listings.engine.stages.placement import ArtworkGroup
from etsy_listings.engine.stages.product_diff import compare
from etsy_listings.engine.stages.product_document import (
    PricedVariant,
    PrintifyProductDesired,
)

BLACK_M = PricedVariant(id=1, colour_slug="black", size="M", price=34900)
BLACK_S = PricedVariant(id=2, colour_slug="black", size="S", price=34900)
WHITE_M = PricedVariant(id=3, colour_slug="white", size="M", price=34900)


def _group(artwork: str = "default", *, design_hash: str = "sha256:abc") -> ArtworkGroup:
    return ArtworkGroup(
        artwork=artwork,
        colours=("black",),
        design=Path(f"{artwork}.png"),
        design_hash=design_hash,
    )


def _desired(*variants: PricedVariant, **overrides: object) -> PrintifyProductDesired:
    fields: dict[str, object] = {
        "title": "Take A Hike Tee",
        "description": "A retro sunset.",
        "blueprint_id": 706,
        "print_provider_id": 29,
        "position": "front",
        "variants": variants or (BLACK_M, BLACK_S),
        "groups": (_group(),),
        "currency": "NOK",
    }
    fields.update(overrides)
    return PrintifyProductDesired(**fields)  # type: ignore[arg-type]


def _live(desired: PrintifyProductDesired, **overrides: object) -> Product:
    """A live product that matches ``desired`` unless told otherwise."""
    fields: dict[str, object] = {
        "id": "abc123",
        "title": desired.title,
        "description": desired.description,
        "visible": False,
        "variants": tuple(
            ProductVariant(id=variant.id, price=variant.price, is_enabled=True)
            for variant in desired.variants
        ),
    }
    fields.update(overrides)
    return Product(**fields)  # type: ignore[arg-type]


# ------------------------------------------------- will_run and reason agree


def test_no_applied_document_means_create() -> None:
    desired = _desired()

    comparison = compare(desired, None, None)

    assert comparison.will_run
    assert comparison.reason is not None
    assert "created" in comparison.reason


def test_an_unchanged_product_runs_for_no_reason_at_all() -> None:
    desired = _desired()

    comparison = compare(desired, desired.applied(), _live(desired))

    assert not comparison.will_run
    assert comparison.reason is None
    assert comparison.changes == ()


def test_a_vanished_product_is_created_again() -> None:
    desired = _desired()

    comparison = compare(desired, desired.applied(), None)

    assert comparison.will_run
    assert comparison.reason is not None
    assert "gone" in comparison.reason


def test_will_run_is_exactly_whether_there_is_a_reason() -> None:
    """The rule had two expressions and they could be edited apart: a stage
    reporting "no changes" while running anyway is what that costs."""
    desired = _desired()
    cases = [
        (None, None),
        (desired.applied(), None),
        (desired.applied(), _live(desired)),
        (
            _desired(PricedVariant(id=1, colour_slug="black", size="M", price=1)).applied(),
            _live(desired),
        ),
    ]

    for was, live in cases:
        comparison = compare(desired, was, live)
        assert comparison.will_run == (comparison.reason is not None)


# ------------------------------------------------------------ price changes


def test_a_price_change_is_reported_in_the_currency_the_listing_wrote() -> None:
    """The document stores minor units; the user wrote `349 NOK`, and that is
    what a diff has to say back."""
    was = _desired(PricedVariant(id=1, colour_slug="black", size="M", price=34900)).applied()
    desired = _desired(PricedVariant(id=1, colour_slug="black", size="M", price=39900))

    changes = compare(desired, was, _live(desired)).changes

    assert changes == (
        PriceChange(
            size="M",
            color="black",
            before=Money(Decimal("349"), "NOK"),
            after=Money(Decimal("399"), "NOK"),
        ),
    )


def test_an_unchanged_price_is_not_a_change() -> None:
    desired = _desired()

    assert compare(desired, desired.applied(), _live(desired)).changes == ()


def test_adding_a_variant_reports_the_count_not_a_price() -> None:
    was = _desired(BLACK_M).applied()
    desired = _desired(BLACK_M, BLACK_S)

    changes = compare(desired, was, _live(desired)).changes

    assert FieldChange(path="variants", before=1, after=2) in changes
    assert not any(isinstance(change, PriceChange) for change in changes)


# ------------------------------------------------------------ colour changes


NAVY_M = PricedVariant(id=3, colour_slug="navy", size="M", price=34900)


def test_a_new_colour_is_reported_by_name() -> None:
    """A30, decision 4: the diff names the colour rather than only a count,
    so the UI does not have to diff two colour lists itself to ring it."""
    was = _desired(BLACK_M).applied()
    desired = _desired(BLACK_M, NAVY_M)

    changes = compare(desired, was, _live(desired)).changes

    assert ListChange(path="colors", added=("navy",), removed=()) in changes


def test_a_removed_colour_is_reported_by_name() -> None:
    was = _desired(BLACK_M, NAVY_M).applied()
    desired = _desired(BLACK_M)

    changes = compare(desired, was, _live(desired)).changes

    assert ListChange(path="colors", added=(), removed=("navy",)) in changes


def test_adding_a_size_in_an_existing_colour_is_not_a_colour_change() -> None:
    """Two sizes, one colour: the variant count changes, the colour set does
    not -- the two are genuinely different questions."""
    was = _desired(BLACK_M).applied()
    desired = _desired(BLACK_M, BLACK_S)

    changes = compare(desired, was, _live(desired)).changes

    assert not any(isinstance(change, ListChange) and change.path == "colors" for change in changes)


def test_an_unchanged_colour_set_is_not_a_change() -> None:
    desired = _desired(BLACK_M, BLACK_S)

    changes = compare(desired, desired.applied(), _live(desired)).changes

    assert not any(isinstance(change, ListChange) and change.path == "colors" for change in changes)


# ------------------------------------------------------------- print areas


def test_reordering_the_listings_colours_is_not_a_print_area_change() -> None:
    """Print areas are matched by ``artwork``, never by position.

    Positional matching read ``was.print_areas[index]``, and that list's order
    followed the order the listing wrote ``colors:`` in -- so moving a colour
    to the top reported every print area as changed and re-uploaded artwork
    nothing about which had moved.
    """
    on_light, on_dark = _group("on-light"), _group("on-dark", design_hash="sha256:def")
    one = _desired(groups=(on_light, on_dark))
    other = _desired(groups=(on_dark, on_light))

    assert compare(other, one.applied(), _live(other)).changes == ()


def test_changed_artwork_names_the_area_it_changed() -> None:
    was = _desired(groups=(_group("on-light", design_hash="sha256:old"),)).applied()
    desired = _desired(groups=(_group("on-light", design_hash="sha256:new"),))

    changes = compare(desired, was, _live(desired)).changes

    assert changes == (
        FieldChange(path="print_areas.on-light", before="sha256:old", after="sha256:new"),
    )


def test_an_artwork_that_no_longer_prints_is_reported() -> None:
    """Positional matching could not see this: a shorter list simply stopped
    being compared, so dropping a print area was silently no change."""
    was = _desired(groups=(_group("on-light"), _group("on-dark"))).applied()
    desired = _desired(groups=(_group("on-light"),))

    changes = compare(desired, was, _live(desired)).changes

    assert FieldChange(path="print_areas.on-dark", before="sha256:abc", after=None) in changes


# ------------------------------------------------------------------- drift


def test_an_edit_in_printify_is_drift_not_a_change() -> None:
    desired = _desired()

    comparison = compare(desired, desired.applied(), _live(desired, title="Edited in Printify"))

    assert Drift(path="title", last_applied="Take A Hike Tee", live="Edited in Printify") in (
        comparison.drift
    )


def test_a_visible_product_is_the_tripwire() -> None:
    desired = _desired()

    comparison = compare(desired, desired.applied(), _live(desired, visible=True))

    assert Drift(path="visible", last_applied=False, live=True) in comparison.drift


def test_no_live_product_is_no_drift() -> None:
    desired = _desired()

    assert compare(desired, desired.applied(), None).drift == ()


def test_a_pending_local_edit_is_not_drift() -> None:
    """A description changed locally but not yet applied must show up as a
    ``change`` (already covered by ``_changes``), never as drift -- drift
    means something moved on Printify/Etsy since the last apply, and nothing
    has here: ``live`` still matches what was last applied."""
    was = _desired(description="Original.")
    desired = _desired(description="Edited locally, not applied yet.")

    comparison = compare(desired, was.applied(), _live(was))

    assert comparison.drift == ()


def test_a_pending_local_colour_addition_is_not_variant_drift() -> None:
    """Same bug, the variant-matrix shape: adding a colour locally, not yet
    applied, must not read as Printify disagreeing about what is enabled --
    ``live`` still matches exactly what was last applied."""
    was = _desired(BLACK_M, BLACK_S)
    desired = _desired(BLACK_M, BLACK_S, WHITE_M)

    comparison = compare(desired, was.applied(), _live(was))

    assert comparison.drift == ()


# ----------------------------------------------------------------- actions


def test_actions_say_create_when_there_is_nothing_to_update() -> None:
    desired = _desired()

    actions = compare(desired, None, None).actions

    assert actions[0].description.startswith("create a Printify product")
    assert actions[0].inputs == ("default.png",)


def test_actions_say_update_when_a_product_is_there() -> None:
    was = _desired(PricedVariant(id=1, colour_slug="black", size="M", price=1)).applied()
    desired = _desired()

    actions = compare(desired, was, _live(desired)).actions

    assert actions[0].description.startswith("update a Printify product")


def test_a_discontinued_cell_is_reported_never_fatal() -> None:
    """PRD 46: a cell Printify has withdrawn is its fact, not the user's
    mistake -- but a listing quietly selling five sizes where it asked for six
    is worth saying out loud."""
    desired = _desired(missing=(("black", "XXXL"),))

    actions = compare(desired, None, None).actions

    assert any("black/XXXL" in action.description for action in actions)

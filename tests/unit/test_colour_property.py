"""Matching Etsy's inventory properties onto this listing's colours.

Thirty lines of scoring that decide which photo each swatch shows, and whose
wrong answer is invisible: a mis-linked variation image is a valid link to the
wrong picture, and nothing in the API objects. Until this module was lifted out
of the `etsy_media` stage the only way to reach it was a full plan-and-execute
against a seeded fake, and the branches that matter most -- the two-way tie and
the empty overlap -- were never exercised at all.
"""

from __future__ import annotations

from etsy_listings.clients.etsy.models import Inventory, InventoryProduct, InventoryPropertyValue
from etsy_listings.config.slug import ColourExceptions
from etsy_listings.engine.stages.colour_property import resolve_colour_property

COLOUR_PROPERTY = 200
SIZE_PROPERTY = 100
NO_EXCEPTIONS = ColourExceptions()


def _inventory(*properties: tuple[int, tuple[str, ...], tuple[int, ...]]) -> Inventory:
    """One product combination carrying the given properties, which is all the
    resolver reads -- it folds every combination's values into one mapping per
    property, so one row states the same thing a full matrix would."""
    return Inventory(
        products=(
            InventoryProduct(
                property_values=tuple(
                    InventoryPropertyValue(property_id=pid, values=values, value_ids=value_ids)
                    for pid, values, value_ids in properties
                )
            ),
        )
    )


def test_the_colour_property_is_the_one_whose_values_are_the_colours() -> None:
    """Never by name or id: ``property_name`` is the blueprint's own option
    name, so it changes with the garment (decision 6)."""
    inventory = _inventory(
        (SIZE_PROPERTY, ("S", "M", "L"), (1, 2, 3)),
        (COLOUR_PROPERTY, ("Black", "Ivory"), (11, 12)),
    )

    resolved = resolve_colour_property(inventory, ("black", "ivory"), NO_EXCEPTIONS)

    assert resolved is not None
    assert resolved.property_id == COLOUR_PROPERTY
    assert resolved.value_id_by_slug == {"black": 11, "ivory": 12}


def test_etsys_own_spelling_is_slugified_to_reach_this_tools_colours() -> None:
    inventory = _inventory((COLOUR_PROPERTY, ("Blue Jean", "Moss"), (21, 22)))

    resolved = resolve_colour_property(inventory, ("blue-jean", "moss"), NO_EXCEPTIONS)

    assert resolved is not None
    assert resolved.value_id_by_slug == {"blue-jean": 21, "moss": 22}


def test_a_colour_that_will_not_slugify_goes_through_the_exceptions() -> None:
    """PRD 7a's sparse table, applied here for the same reason the mockup
    filenames apply it: the convention covers almost everything, and the
    exceptions file covers what it cannot."""
    exceptions = ColourExceptions({"Heather Grey/Black": "heather-grey-black"})
    inventory = _inventory((COLOUR_PROPERTY, ("Heather Grey/Black",), (31,)))

    resolved = resolve_colour_property(inventory, ("heather-grey-black",), exceptions)

    assert resolved is not None
    assert resolved.value_id_by_slug == {"heather-grey-black": 31}


def test_the_best_overlap_wins_when_one_property_is_clearly_it() -> None:
    """A size property whose values happen to include one colour word does not
    beat the property that matches three of them."""
    inventory = _inventory(
        (SIZE_PROPERTY, ("black", "M", "L"), (1, 2, 3)),
        (COLOUR_PROPERTY, ("Black", "Ivory", "Moss"), (11, 12, 13)),
    )

    resolved = resolve_colour_property(inventory, ("black", "ivory", "moss"), NO_EXCEPTIONS)

    assert resolved is not None
    assert resolved.property_id == COLOUR_PROPERTY


def test_nothing_overlapping_is_no_answer_rather_than_a_wrong_one() -> None:
    inventory = _inventory((SIZE_PROPERTY, ("S", "M", "L"), (1, 2, 3)))

    assert resolve_colour_property(inventory, ("black", "ivory"), NO_EXCEPTIONS) is None


def test_two_properties_matching_equally_is_refused_not_guessed() -> None:
    """The branch that made this worth its own module. Picking either would
    link every swatch to a plausible-looking wrong photo, and Etsy would report
    nothing at all -- so the caller says "skipped" instead."""
    inventory = _inventory(
        (SIZE_PROPERTY, ("Black", "Ivory"), (1, 2)),
        (COLOUR_PROPERTY, ("Black", "Ivory"), (11, 12)),
    )

    assert resolve_colour_property(inventory, ("black", "ivory"), NO_EXCEPTIONS) is None


def test_a_property_matching_only_some_colours_still_answers() -> None:
    """A listing may sell four colours where Etsy's inventory carries three --
    the overlap is what identifies the property, not a complete match."""
    inventory = _inventory((COLOUR_PROPERTY, ("Black", "Ivory"), (11, 12)))

    resolved = resolve_colour_property(inventory, ("black", "ivory", "moss"), NO_EXCEPTIONS)

    assert resolved is not None
    assert "moss" not in resolved.value_id_by_slug


def test_mismatched_value_lists_are_ignored_rather_than_fatal() -> None:
    """``values`` and ``value_ids`` are two parallel lists in Etsy's response.
    One property arriving ragged must not fail the whole media sync."""
    inventory = _inventory(
        (SIZE_PROPERTY, ("S", "M"), ()),
        (COLOUR_PROPERTY, ("Black", "Ivory"), (11, 12)),
    )

    resolved = resolve_colour_property(inventory, ("black", "ivory"), NO_EXCEPTIONS)

    assert resolved is not None
    assert resolved.property_id == COLOUR_PROPERTY

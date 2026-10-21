"""ADR-0053: the one listing-level artwork resolver.

Every row of the spec's resolution examples (docs/features/multi-artwork-20260928/spec.md, *The
listing document* and *Artwork resolution*), each `Resolution` variant,
`slot_users` ignoring exceptions and `representative`'s order. Pure: no
workspace, no files -- the map, a colour and the profile's tones.
"""

from __future__ import annotations

import pytest

from etsy_listings.core.config.artwork import (
    NeedsColour,
    NoDesign,
    Resolved,
    SlotEmpty,
    Tone,
    Unclassified,
    representative,
    resolve,
    slot_users,
)

TAKE_A_HIKE = "designs/take-a-hike.png"
DARK_INK = "designs/take-a-hike-dark-ink.png"
LIGHT_INK = "designs/take-a-hike-light-ink.png"
MOSS_SPECIAL = "designs/take-a-hike-moss-special.png"
IVORY_SPECIAL = "designs/take-a-hike-ivory-special.png"

TONES: dict[str, Tone] = {"ivory": "light", "natural": "light", "black": "dark", "moss": "dark"}


@pytest.mark.parametrize(
    ("design", "colour", "expected"),
    [
        # One base artwork: every enabled colour uses the same file.
        ({"default": TAKE_A_HIKE}, "black", Resolved(TAKE_A_HIKE, "default")),
        ({"default": TAKE_A_HIKE}, "ivory", Resolved(TAKE_A_HIKE, "default")),
        # One base artwork with a colour exception.
        (
            {"default": TAKE_A_HIKE, "moss": MOSS_SPECIAL},
            "moss",
            Resolved(MOSS_SPECIAL, "colour"),
        ),
        (
            {"default": TAKE_A_HIKE, "moss": MOSS_SPECIAL},
            "black",
            Resolved(TAKE_A_HIKE, "default"),
        ),
        # Light and dark base artwork, named for the shirt they print on.
        ({"on-light": DARK_INK, "on-dark": LIGHT_INK}, "ivory", Resolved(DARK_INK, "on-light")),
        ({"on-light": DARK_INK, "on-dark": LIGHT_INK}, "black", Resolved(LIGHT_INK, "on-dark")),
        ({"on-light": DARK_INK, "on-dark": LIGHT_INK}, "moss", Resolved(LIGHT_INK, "on-dark")),
        # Light and dark with a colour exception: moss ignores its tone.
        (
            {"on-light": DARK_INK, "on-dark": LIGHT_INK, "moss": MOSS_SPECIAL},
            "moss",
            Resolved(MOSS_SPECIAL, "colour"),
        ),
        (
            {"on-light": DARK_INK, "on-dark": LIGHT_INK, "moss": MOSS_SPECIAL},
            "ivory",
            Resolved(DARK_INK, "on-light"),
        ),
        # A partial pair: nothing chosen yet, then one slot chosen.
        ({"on-light": None, "on-dark": None}, "ivory", SlotEmpty("light")),
        ({"on-light": None, "on-dark": None}, "black", SlotEmpty("dark")),
        ({"on-dark": LIGHT_INK}, "black", Resolved(LIGHT_INK, "on-dark")),
        ({"on-dark": LIGHT_INK}, "ivory", SlotEmpty("light")),
        # A direct exception is considered before the base slots.
        (
            {"on-dark": LIGHT_INK, "ivory": IVORY_SPECIAL},
            "ivory",
            Resolved(IVORY_SPECIAL, "colour"),
        ),
    ],
)
def test_the_spec_resolution_examples(
    design: dict[str, str | None], colour: str, expected: object
) -> None:
    assert resolve(design, colour, TONES) == expected


def test_no_design_resolves_to_nothing() -> None:
    assert resolve({}, "black", TONES) == NoDesign()
    assert resolve({}, None, TONES) == NoDesign()


def test_an_unclassified_colour_in_light_dark_mode_is_unclassified() -> None:
    design = {"on-light": DARK_INK, "on-dark": LIGHT_INK}
    assert resolve(design, "heather", TONES) == Unclassified("heather")


def test_an_unclassified_colour_needs_no_tone_in_single_mode() -> None:
    """Resolution itself asks for a tone only when there is a pair to pick
    from; the mandatory-classification rule is validation's, not this one's."""
    assert resolve({"default": TAKE_A_HIKE}, "heather", TONES) == Resolved(TAKE_A_HIKE, "default")


def test_an_exception_resolves_even_for_an_unclassified_colour() -> None:
    design = {"on-dark": LIGHT_INK, "heather": MOSS_SPECIAL}
    assert resolve(design, "heather", TONES) == Resolved(MOSS_SPECIAL, "colour")


def test_a_colourless_scene_prints_default_in_single_mode() -> None:
    design = {"default": TAKE_A_HIKE, "moss": MOSS_SPECIAL}
    assert resolve(design, None, TONES) == Resolved(TAKE_A_HIKE, "default")


def test_a_colourless_scene_cannot_resolve_in_light_dark_mode() -> None:
    """The tool does not guess which base file a photograph shows."""
    assert resolve({"on-light": DARK_INK, "on-dark": LIGHT_INK}, None, TONES) == NeedsColour()
    assert resolve({"on-light": None, "on-dark": None}, None, TONES) == NeedsColour()


def test_slot_users_counts_only_automatic_enabled_colours() -> None:
    design = {"on-dark": LIGHT_INK, "ivory": IVORY_SPECIAL}
    users = slot_users(design, ["ivory", "black", "moss", "heather"], TONES)
    assert users == {"light": [], "dark": ["black", "moss"]}


def test_slot_users_keeps_enabled_order() -> None:
    users = slot_users({"default": TAKE_A_HIKE}, ["moss", "natural", "black", "ivory"], TONES)
    assert users == {"light": ["natural", "ivory"], "dark": ["moss", "black"]}


@pytest.mark.parametrize(
    ("design", "expected"),
    [
        ({"default": TAKE_A_HIKE, "moss": MOSS_SPECIAL}, TAKE_A_HIKE),
        ({"on-light": DARK_INK, "on-dark": LIGHT_INK}, DARK_INK),
        ({"on-dark": LIGHT_INK, "on-light": DARK_INK}, DARK_INK),
        ({"on-light": None, "on-dark": LIGHT_INK}, LIGHT_INK),
        ({"on-light": None, "on-dark": None}, None),
        ({"on-dark": LIGHT_INK, "ivory": IVORY_SPECIAL}, LIGHT_INK),
        ({"moss": MOSS_SPECIAL}, None),
        ({}, None),
    ],
)
def test_representative_is_default_then_on_light_then_on_dark(
    design: dict[str, str | None], expected: str | None
) -> None:
    """Colour keys are never promoted (spec: *Representative artwork*)."""
    assert representative(design) == expected

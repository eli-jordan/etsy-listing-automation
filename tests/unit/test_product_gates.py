"""The three things `plan` refuses before any remote write.

Each exists because nothing downstream would catch the mistake. Printify
accepted a 120x140 PNG onto a 4200x4800 print area without a warning; it
answers 200 to a blueprint change and silently ignores it; and it requires a
title, so a `<generate>` sentinel would be published as the literal string.

A gate *returns* its refusal rather than raising it. That is what lets `plan`
report the blocked stage alongside everything else the run would do, instead
of dying on the first one -- so these tests read the refusal as a value, and
the message is the whole of what they check.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from etsy_listings.config.profile import BlueprintRef, PrintArea, Profile
from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.gates import (
    check_copy_is_concrete,
    check_design_resolution,
    check_garment_unchanged,
)

PROFILE = Profile(
    blueprint=BlueprintRef(brand="Comfort Colors", model="1717"),
    print_provider="Monster Digital",
    placeholder="front",
    print_area=PrintArea(width=4200, height=4800),
    sizes=["S", "M", "L"],
)


def _design(tmp_path: Path, size: tuple[int, int], mode: str = "RGBA") -> Path:
    path = tmp_path / "design.png"
    Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0)).save(path)
    return path


def _refusal(blocked: Blocked | None) -> str:
    """The message of a refusal that must have happened."""
    assert blocked is not None, "expected the gate to refuse"
    return blocked.message


# ------------------------------------------------- design resolution (PRD 38)


def test_a_design_at_the_print_area_passes(tmp_path: Path) -> None:
    assert check_design_resolution(_design(tmp_path, (4200, 4800)), PROFILE) is None


def test_a_design_within_ten_percent_passes(tmp_path: Path) -> None:
    """The workspace's own 4000x4800 file against a 4200x4800 area -- 4.8%
    short, invisible in print. A gate that rejects it is a gate that gets
    switched off."""
    assert check_design_resolution(_design(tmp_path, (4000, 4800)), PROFILE) is None


def test_a_design_larger_than_the_print_area_passes(tmp_path: Path) -> None:
    """The rule is a floor, not a target: extra pixels cost nothing."""
    assert check_design_resolution(_design(tmp_path, (8400, 9600)), PROFILE) is None


@pytest.mark.parametrize("size", [(3779, 4800), (4200, 4319), (120, 140)])
def test_a_design_short_on_either_axis_is_refused(tmp_path: Path, size) -> None:
    assert check_design_resolution(_design(tmp_path, size), PROFILE) is not None


def test_the_refusal_names_the_size_it_wanted(tmp_path: Path) -> None:
    """ "Too small" sends someone back to the tool. The required number sends
    them back to their design software, which is where the fix is."""
    message = _refusal(check_design_resolution(_design(tmp_path, (120, 140)), PROFILE))

    assert "120" in message and "140" in message
    assert "3780" in message and "4320" in message, "the 90% floor, spelled out"
    assert "4200" in message and "4800" in message, "and the print area it came from"


def test_a_design_without_an_alpha_channel_is_refused(tmp_path: Path) -> None:
    """A print file with no transparency prints its background as a rectangle
    of ink on the shirt."""
    opaque = _design(tmp_path, (4200, 4800), mode="RGB")

    assert "alpha" in _refusal(check_design_resolution(opaque, PROFILE))


def test_a_missing_design_is_refused_by_name(tmp_path: Path) -> None:
    assert "nope.png" in _refusal(check_design_resolution(tmp_path / "nope.png", PROFILE))


def test_a_file_that_is_not_an_image_is_refused(tmp_path: Path) -> None:
    """A .png that is really a text file is a mistake worth naming rather
    than a traceback out of Pillow."""
    path = tmp_path / "design.png"
    path.write_text("not a png", encoding="utf-8")

    assert "not readable as an image" in _refusal(check_design_resolution(path, PROFILE))


# ---------------------------------------------------- garment change (PRD 37)


APPLIED = {"blueprint_id": 706, "print_provider_id": 29}


def test_an_unchanged_garment_passes() -> None:
    assert check_garment_unchanged(APPLIED, blueprint_id=706, print_provider_id=29) is None


def test_no_previous_apply_passes() -> None:
    """Nothing to have changed from. The first `apply` creates the product."""
    assert check_garment_unchanged(None, blueprint_id=706, print_provider_id=29) is None


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


# ------------------------------------------------------ concrete copy (PRD 44)


def test_real_copy_passes() -> None:
    assert check_copy_is_concrete(title="Take A Hike Tee", description="A retro sunset.") is None


@pytest.mark.parametrize("title", ["<generate>", "", "   "])
def test_an_unresolved_or_empty_title_is_refused(title: str) -> None:
    assert "title" in _refusal(check_copy_is_concrete(title=title, description="A retro sunset."))


@pytest.mark.parametrize("description", ["<generate>", "", "   "])
def test_an_unresolved_or_empty_description_is_refused(description: str) -> None:
    assert "description" in _refusal(
        check_copy_is_concrete(title="Take A Hike Tee", description=description)
    )


def test_the_refusal_says_why_a_product_needs_them() -> None:
    """Not obvious: PRD 41 says copy is ours and goes straight to Etsy. It is
    needed here because Printify's create call requires it and because it is
    the duplicate guard's match key (PRD 48)."""
    message = _refusal(check_copy_is_concrete(title="<generate>", description="x"))

    assert "Printify" in message
    assert "generate" in message.lower()


# ------------------------------------------- the refusal's shape (cli.render)


def test_a_refusal_leads_with_the_consequence_and_follows_with_the_remedy(
    tmp_path: Path,
) -> None:
    """`cli.render` indents everything after the first line as the remedy, so
    a refusal that buries the consequence on line two renders as a heading
    that says nothing."""
    message = _refusal(check_design_resolution(_design(tmp_path, (120, 140)), PROFILE))
    head, *rest = message.splitlines()

    assert "too small" in head
    assert rest, "a refusal a user can act on says what to do about it"
    assert not any(line.startswith(" ") for line in rest), "cli.render owns the indenting"

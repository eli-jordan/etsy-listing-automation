"""The `new` wizard's picker rows: designs, garments and pricing plans as
the terminal lists them -- order, columns and markers. No live Printify
catalog and no terminal. The core operations behind the rows live with their
owners (test-suite quality plan, PR 9): ``tests/core/unit/test_garment_profiles.py``,
``test_listing_stubs.py``, ``test_starting_prices.py`` and ``test_workspace.py``."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from etsy_listings.cli.pickers import (
    build_blueprint_choices,
    build_design_choices,
    build_pricing_plan_choices,
)
from etsy_listings.core.application.garment_profiles import local_blueprint_keys
from etsy_listings.core.clients.printify.models import Blueprint
from etsy_listings.core.clients.printify.resolve import normalise
from etsy_listings.core.config.money import Money
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.workspace.workspace import Workspace

# --- pricing plans -----------------------------------------------


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


# --- the garment rows, and which count as "already used here" ----------------
#
# Moved here from the prompts file, where they sat because the marker glyph is
# printed by a picker. They are about the picker rows, which is what this file
# tests; the glyph is `terminal`'s, tested in tests/cli/unit/test_terminal.py.

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

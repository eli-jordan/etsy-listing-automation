"""Listing positions retain absolute geometry without changing production fields."""

import pytest
from pydantic import ValidationError

from etsy_listings.core.config.listing import Listing
from etsy_listings.core.config.template_positions import (
    BoxPosition,
    PlacementPositions,
    TemplatePositions,
    layer_boxes,
)
from etsy_listings.core.render.config import BoundingBox

BOX = [{"x": 10, "y": 20}, {"x": 110, "y": 20}, {"x": 110, "y": 220}, {"x": 10, "y": 220}]


def test_positions_are_optional_and_round_trip_both_template_shapes() -> None:
    listing = Listing.empty_draft(currency="NOK")
    assert listing.template_positions is None
    positions = {
        "flat": {"bounding_box": BOX},
        "chart": {"placements": {"left": {"bounding_box": BOX}}},
    }
    positioned = Listing.model_validate({**listing.model_dump(), "template_positions": positions})
    assert positioned.model_dump(mode="json")["template_positions"] == positions


@pytest.mark.parametrize("position", [{}, {"bounding_box": BOX, "placements": {}}, {"bogus": BOX}])
def test_each_position_has_exactly_one_shape(position: object) -> None:
    with pytest.raises(ValidationError):
        Listing.model_validate(
            {
                **Listing.empty_draft(currency="NOK").model_dump(),
                "template_positions": {"flat": position},
            }
        )


def test_layer_boxes_key_one_box_by_none_and_placement_boxes_by_id() -> None:
    box = BoxPosition.model_validate({"bounding_box": BOX}).bounding_box
    positions: TemplatePositions = {
        "flat": BoxPosition(bounding_box=box),
        "chart": PlacementPositions.model_validate({"placements": {"left": {"bounding_box": BOX}}}),
    }

    assert layer_boxes(positions, "flat") == {None: box}
    assert layer_boxes(positions, "chart") == {"left": box}


def test_a_template_the_listing_positions_nothing_for_keeps_its_own_boxes() -> None:
    no_boxes: dict[str | None, BoundingBox] = {}
    assert layer_boxes(None, "flat") == no_boxes
    assert layer_boxes({}, "flat") == no_boxes

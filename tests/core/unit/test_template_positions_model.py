"""Listing positions retain absolute geometry without changing production fields."""

import pytest
from pydantic import ValidationError

from etsy_listings.core.config.listing import Listing

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

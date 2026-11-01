"""The saved numerical inputs shared by preview and durable preparation."""

from etsy_listings.core.preparation.artifacts import PlacementInput
from etsy_listings.core.render.config import Point


def test_placement_input_preserves_quad_order_and_evidence():
    box = tuple(Point(x=x, y=y) for x, y in [(1, 2), (9, 2), (8, 7), (0, 6)])
    value = PlacementInput.from_box("front", box, mask="1" * 64, evidence="2" * 64)
    assert value.quad == ((1, 2), (9, 2), (8, 7), (0, 6))
    assert value.id == "front"
    assert value.mask == "1" * 64
    assert value.evidence == "2" * 64

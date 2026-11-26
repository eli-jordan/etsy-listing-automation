"""Following a mockup template's rename through a listing-shaped document."""

from __future__ import annotations

from typing import Any

from etsy_listings.core.config.template_refs import rename_template_refs

BOX = [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}]


def _document(template: str) -> dict[str, Any]:
    return {
        "media": [{"template": template, "colour": "black"}, "common-media/chart.png"],
        "etsy": {"variation_images": template},
        "template_positions": {template: {"bounding_box": BOX}, "other": {"bounding_box": BOX}},
    }


def test_media_variation_images_and_position_keys_follow_a_rename() -> None:
    assert rename_template_refs(_document("flat"), "flat", "flat-lay") == _document("flat-lay")


def test_the_document_passed_in_is_left_as_it_was() -> None:
    document = _document("flat")

    rename_template_refs(document, "flat", "flat-lay")

    assert document == _document("flat")


def test_a_document_that_does_not_name_the_template_gives_none() -> None:
    assert rename_template_refs(_document("other-template"), "flat", "flat-lay") is None


def test_a_document_that_would_not_load_still_follows() -> None:
    document = {**_document("flat"), "colors": "not a list", "prices": 5}

    renamed = rename_template_refs(document, "flat", "flat-lay")

    assert renamed == {**_document("flat-lay"), "colors": "not a list", "prices": 5}

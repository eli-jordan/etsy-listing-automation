"""`ListingTemplate`, the model of `listing-templates/<name>/template.yaml`
(ADR-0047; spec *Listing templates*).

It is not a `Listing` with placeholders: the design, the brief and the SEO
copy are not fields it has, so a document naming them is refused rather than
quietly carried. The structural rules it shares with a listing -- the gallery
layout, currencies, colours that exist -- are the listing's own, not a copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.listing_template import ListingTemplate
from etsy_listings.config.money import Money

BASE: dict[str, object] = {
    "garment_profile": "comfort-colors-1717",
    "colors": ["black", "ivory"],
    "prices": {"S": "349 NOK"},
    "media": [{"template": "flat-lay-01", "colour": "black"}],
}


def _load(document: dict[str, object]) -> ListingTemplate:
    return ListingTemplate.model_validate(document, context={"currency": "NOK"})


def test_a_template_holds_the_reusable_production_settings() -> None:
    template = _load(
        {
            **BASE,
            "pricing_plan": "pricing-plans/standard.yaml",
            "price_overrides": {"black": {"XL": "369 NOK"}},
            "etsy": {
                "description": {"ref": "common-copy/care.md"},
                "renewal": "auto",
                "section": "Hiking tees",
                "shipping_profile": "NOK heavy tee",
                "variation_images": "flat-lay-01",
            },
        }
    )

    assert template.prices == {"S": Money.parse("349 NOK")}
    assert template.price_overrides == {"black": {"XL": Money.parse("369 NOK")}}
    assert template.etsy.description.ref == "common-copy/care.md"
    assert template.etsy.section == "Hiking tees"


@pytest.mark.parametrize(
    "extra",
    [
        {"design": "designs/take-a-hike.png"},
        {"brief": "a brief"},
        {"artwork": {"black": "default"}},
        {"lifecycle": "retired"},
        {"etsy": {"title": "A title"}},
        {"etsy": {"tags": ["hiking"]}},
        {"etsy": {"description": {"lead": "An opening line."}}},
    ],
)
def test_design_specific_fields_are_not_part_of_a_template(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _load({**BASE, **extra})


def test_a_description_body_is_text_or_a_ref_never_both() -> None:
    with pytest.raises(ValidationError, match="text and ref"):
        _load({**BASE, "etsy": {"description": {"text": "Body", "ref": "common-copy/x.md"}}})


def test_it_shares_the_listing_gallery_rules() -> None:
    with pytest.raises(ValidationError, match="position 1"):
        _load({**BASE, "media": ["common-media/intro.mp4"]})


def test_it_shares_the_listing_currency_rule() -> None:
    with pytest.raises(ValidationError, match="USD"):
        _load({**BASE, "prices": {"S": "20 USD"}})


def test_a_media_colour_must_be_one_the_template_sells() -> None:
    with pytest.raises(ValidationError, match="not in colors"):
        _load({**BASE, "media": [{"template": "flat-lay-01", "colour": "moss"}]})


def test_load_names_the_file_it_could_not_read(tmp_path: Path) -> None:
    path = tmp_path / "template.yaml"
    path.write_text("garment_profile: x\ncolors: []\nmedia: []\nbrief: no\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="template.yaml"):
        ListingTemplate.load(path, currency="NOK")

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etsy_listings.config.description import DescriptionConfig
from etsy_listings.config.listing import (
    EMPTY_DRAFT,
    MAX_MEDIA_ENTRIES,
    EtsyListingConfig,
    Listing,
    TemplateMediaEntry,
)
from etsy_listings.config.money import Money
from etsy_listings.config.pricing_plan import PricingPlan

BASE: dict[str, object] = {
    "garment_profile": "comfort-colors-1717",
    "design": "../../designs/take-a-hike.png",
    "colors": ["black"],
    "brief": "test brief",
    "prices": {"S": "349 NOK"},
    "media": [{"template": "flat-lay-01", "colour": "black"}],
}


def test_loads_valid_listing(workspace_root: Path) -> None:
    path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    listing = Listing.load(path, currency="NOK")
    assert listing.garment_profile == "comfort-colors-1717"
    assert listing.resolved_price("black", "XL") == Money.parse("359 NOK")


# -------------------------------------------------- per-listing Etsy overrides


def test_etsy_overrides_default_to_unset() -> None:
    """No shop section, no shipping-profile override, no variation-images
    template -- a listing that never mentions `etsy:` inherits everything
    from `shop.yaml`'s `listing_defaults` (decision 2)."""
    config = EtsyListingConfig()
    assert (config.section, config.shipping_profile, config.variation_images) == (None, None, None)


def test_a_listing_can_override_section_shipping_profile_and_variation_images() -> None:
    data = {
        **BASE,
        "etsy": {
            "section": "Retro Tees",
            "shipping_profile": "NOK heavy tee",
            "variation_images": "flat-lay-01",
        },
    }
    listing = Listing.model_validate(data, context={"currency": "NOK"})

    assert listing.etsy.section == "Retro Tees"
    assert listing.etsy.shipping_profile == "NOK heavy tee"
    assert listing.etsy.variation_images == "flat-lay-01"


def test_listing_materials_explains_the_garment_profile_migration() -> None:
    with pytest.raises(ValidationError, match="moved to the garment profile"):
        Listing.model_validate(
            {**BASE, "etsy": {"materials": ["cotton"]}}, context={"currency": "NOK"}
        )


def test_bare_design_string_normalises_to_default_key() -> None:
    listing = Listing.model_validate(BASE, context={"currency": "NOK"})
    assert listing.design == {"default": "../../designs/take-a-hike.png"}


def test_design_map_is_kept_as_is() -> None:
    data = {
        **BASE,
        "design": {
            "on-light": "../../designs/take-a-hike-dark-ink.png",
            "on-dark": "../../designs/take-a-hike-light-ink.png",
        },
    }
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    assert listing.design == {
        "on-light": "../../designs/take-a-hike-dark-ink.png",
        "on-dark": "../../designs/take-a-hike-light-ink.png",
    }


def test_rejects_bare_number_price_naming_the_field() -> None:
    data = {**BASE, "prices": {"S": 349}}
    with pytest.raises(ValidationError) as exc_info:
        Listing.model_validate(data, context={"currency": "NOK"})
    message = str(exc_info.value)
    assert "prices" in message
    assert "S" in message


def test_rejects_currency_mismatch_naming_field_and_expected_currency() -> None:
    data = {**BASE, "prices": {"S": "349 USD"}}
    with pytest.raises(ValidationError) as exc_info:
        Listing.model_validate(data, context={"currency": "NOK"})
    message = str(exc_info.value)
    assert "prices.S" in message
    assert "USD" in message
    assert "NOK" in message


def test_rejects_price_override_currency_mismatch() -> None:
    data = {
        **BASE,
        "colors": ["black", "ice-blue"],
        "price_overrides": {"ice-blue": {"XXL": "379 USD"}},
    }
    with pytest.raises(ValidationError) as exc_info:
        Listing.model_validate(data, context={"currency": "NOK"})
    assert "price_overrides.ice-blue.XXL" in str(exc_info.value)


def test_rejects_media_referencing_unlisted_colour() -> None:
    data = {**BASE, "media": [{"template": "flat-lay-01", "colour": "not-a-listed-colour"}]}
    with pytest.raises(ValidationError, match="not-a-listed-colour"):
        Listing.model_validate(data, context={"currency": "NOK"})


def test_media_entry_without_colour_is_valid_for_non_colour_matrix_templates() -> None:
    data = {**BASE, "media": [{"template": "colour-chart-01"}]}
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    entry = listing.media[0]
    assert isinstance(entry, TemplateMediaEntry)
    assert entry.colour is None


def test_media_shared_asset_path_still_works() -> None:
    data = {**BASE, "media": [*BASE["media"], "../../common-media/sizing-chart.png"]}
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    assert listing.media[1] == "../../common-media/sizing-chart.png"


def test_rejects_more_than_max_media_entries() -> None:
    data = {
        **BASE,
        "media": [f"common-media/asset-{i}.png" for i in range(MAX_MEDIA_ENTRIES + 1)],
    }
    with pytest.raises(ValidationError, match=f"{MAX_MEDIA_ENTRIES}-image limit"):
        Listing.model_validate(data, context={"currency": "NOK"})


def test_etsy_defaults_to_empty_ordinary_values_not_a_sentinel() -> None:
    """`<generate>` is gone: an unset listing's title, tags and description
    are ordinary empty values, not a literal the editor has to special-case."""
    config = EtsyListingConfig()
    assert config.title == ""
    assert config.tags == []
    assert config.description == DescriptionConfig()


def test_a_listing_can_set_a_structured_description() -> None:
    data = {
        **BASE,
        "etsy": {"description": {"lead": "A relaxed tee.", "text": "Printed to order."}},
    }
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    assert listing.etsy.description.lead == "A relaxed tee."
    assert listing.etsy.description.text == "Printed to order."


def test_a_listing_can_set_a_common_copy_ref() -> None:
    data = {**BASE, "etsy": {"description": {"lead": "", "ref": "common-copy/comfort-colors.md"}}}
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    assert listing.etsy.description.ref == "common-copy/comfort-colors.md"


def test_a_listing_rejects_text_and_ref_together() -> None:
    data = {
        **BASE,
        "etsy": {"description": {"lead": "x", "text": "inline", "ref": "common-copy/x.md"}},
    }
    with pytest.raises(ValidationError, match="text and ref"):
        Listing.model_validate(data, context={"currency": "NOK"})


def test_rejects_more_than_thirteen_tags() -> None:
    data = {**BASE, "etsy": {"tags": [f"tag{i}" for i in range(14)]}}
    with pytest.raises(ValidationError, match="13-tag limit"):
        Listing.model_validate(data, context={"currency": "NOK"})


def test_artwork_override_accepts_listed_colour() -> None:
    data = {**BASE, "artwork": {"black": "on-dark"}}
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    assert listing.artwork == {"black": "on-dark"}


def test_rejects_artwork_override_for_unlisted_colour() -> None:
    data = {**BASE, "artwork": {"not-a-listed-colour": "on-dark"}}
    with pytest.raises(ValidationError, match="not-a-listed-colour"):
        Listing.model_validate(data, context={"currency": "NOK"})


def test_load_missing_file_raises_actionable_error(tmp_path: Path) -> None:
    from etsy_listings.config.errors import ConfigLoadError

    with pytest.raises(ConfigLoadError, match="not found"):
        Listing.load(tmp_path / "missing.yaml", currency="NOK")


def test_load_wraps_validation_error_with_path(tmp_path: Path) -> None:
    from etsy_listings.config.errors import ConfigLoadError

    bad_path = tmp_path / "listing.yaml"
    bad_path.write_text(yaml.safe_dump({**BASE, "prices": {"S": 349}}))
    with pytest.raises(ConfigLoadError) as exc_info:
        Listing.load(bad_path, currency="NOK")
    assert str(bad_path) in str(exc_info.value)


# --- pricing plans: prices becomes optional, resolved_price gains a fallback tier ---


def test_pricing_plan_defaults_to_none() -> None:
    listing = Listing.model_validate(BASE, context={"currency": "NOK"})
    assert listing.pricing_plan is None


def test_a_listing_with_neither_pricing_plan_nor_prices_still_parses() -> None:
    """PRD 70: this model stopped owning the price-source refusal. It is a
    `listing_validation.check_price_source` block issue and a
    `gates.check_price_source` refusal -- the same two places every other
    incompleteness is reported from -- so the file is written and the deploy
    is what stops."""
    data = {**BASE}
    del data["prices"]

    listing = Listing.model_validate(data, context={"currency": "NOK"})

    assert listing.pricing_plan is None
    assert listing.prices == {}


def test_a_pricing_plan_reference_alone_leaves_prices_empty() -> None:
    data = {**BASE}
    del data["prices"]
    data["pricing_plan"] = "../../pricing-plans/launch-low.yaml"
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    assert listing.prices == {}


def test_resolved_price_prefers_listing_price_overrides_over_everything() -> None:
    data = {
        **BASE,
        "colors": ["black"],
        "prices": {"S": "349 NOK"},
        "price_overrides": {"black": {"S": "300 NOK"}},
    }
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    plan = PricingPlan(garment_profile="comfort-colors-1717", prices={"S": Money.parse("100 NOK")})
    assert listing.resolved_price("black", "S", pricing_plan=plan) == Money.parse("300 NOK")


def test_resolved_price_prefers_listing_prices_over_the_plan() -> None:
    data = {**BASE, "prices": {"S": "349 NOK"}}
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    plan = PricingPlan(garment_profile="comfort-colors-1717", prices={"S": Money.parse("100 NOK")})
    assert listing.resolved_price("black", "S", pricing_plan=plan) == Money.parse("349 NOK")


def test_resolved_price_falls_back_to_the_plan_when_listing_has_no_price() -> None:
    data = {**BASE}
    del data["prices"]
    data["pricing_plan"] = "../../pricing-plans/launch-low.yaml"
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    plan = PricingPlan(garment_profile="comfort-colors-1717", prices={"S": Money.parse("100 NOK")})
    assert listing.resolved_price("black", "S", pricing_plan=plan) == Money.parse("100 NOK")


def test_resolved_price_uses_the_plans_own_colour_override() -> None:
    data = {**BASE}
    del data["prices"]
    data["pricing_plan"] = "../../pricing-plans/launch-low.yaml"
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    plan = PricingPlan(
        garment_profile="comfort-colors-1717",
        prices={"S": Money.parse("100 NOK")},
        price_overrides={"black": {"S": "120 NOK"}},
    )
    assert listing.resolved_price("black", "S", pricing_plan=plan) == Money.parse("120 NOK")


def test_resolved_price_raises_when_nothing_covers_the_size() -> None:
    data = {**BASE}
    del data["prices"]
    data["pricing_plan"] = "../../pricing-plans/launch-low.yaml"
    listing = Listing.model_validate(data, context={"currency": "NOK"})
    plan = PricingPlan(garment_profile="comfort-colors-1717", prices={"S": Money.parse("100 NOK")})
    with pytest.raises(KeyError):
        listing.resolved_price("black", "XXXL", pricing_plan=plan)


def test_resolved_price_raises_without_a_plan_when_the_size_is_missing() -> None:
    listing = Listing.model_validate(BASE, context={"currency": "NOK"})
    with pytest.raises(KeyError):
        listing.resolved_price("black", "XXXL")


# ------------------------------------------------------- the unsaved draft


def test_lifecycle_is_omitted_on_a_working_listing() -> None:
    """Named `lifecycle`, not `status`: the table already has a Status column
    (PRD 62). Working listings do not carry a third value."""
    listing = Listing.model_validate(BASE, context={"currency": "NOK"})
    assert listing.lifecycle is None


@pytest.mark.parametrize("value", ["retired", "deleted", "renew"])
def test_lifecycle_accepts_the_three_marks(value: str) -> None:
    listing = Listing.model_validate({**BASE, "lifecycle": value}, context={"currency": "NOK"})
    assert listing.lifecycle == value


def test_lifecycle_rejects_a_working_state_written_as_a_value() -> None:
    """Un-retire is deleting the key, not writing `active`."""
    with pytest.raises(ValidationError):
        Listing.model_validate({**BASE, "lifecycle": "active"}, context={"currency": "NOK"})


def test_an_empty_draft_builds_with_nothing_chosen() -> None:
    """What `+ New listing` opens on. Every field is empty rather than
    invented, and nothing about being empty is a validation failure."""
    draft = Listing.empty_draft(currency="NOK")
    assert draft.garment_profile == ""
    assert draft.design == {}
    assert draft.colors == []
    assert draft.media == []
    assert draft.pricing_plan is None
    assert draft.prices == {}
    assert draft.etsy.title == ""
    assert draft.etsy.description == DescriptionConfig()


def test_the_empty_document_validates_as_an_ordinary_listing() -> None:
    """PRD 70: incompleteness is not a validation failure, so there is no
    separate draft rule and nothing for one to waive. An empty document is a
    listing that has nothing chosen yet -- the banner says what is missing,
    and the stages refuse to deploy it."""
    listing = Listing.model_validate(EMPTY_DRAFT, context={"currency": "NOK"})

    assert listing.pricing_plan is None
    assert listing.prices == {}


@pytest.mark.parametrize(
    ("over", "expected_in_message"),
    [
        ({"media": [{"template": "flat-lay-01", "colour": "ivory"}]}, "ivory"),
        ({"price_overrides": {"ivory": {"S": "349 NOK"}}}, "ivory"),
        ({"artwork": {"ivory": "on-light"}}, "ivory"),
        ({"prices": {"S": "349 USD"}}, "NOK"),
        ({"etsy": {"title": "x" * 141}}, "140"),
    ],
)
def test_an_incomplete_listing_still_cannot_contradict_itself(
    over: dict[str, object], expected_in_message: str
) -> None:
    """The line PRD 70 draws: *incomplete* is fine, *malformed* is not.

    Every case here is a field somebody filled in that disagrees with another
    one -- a colour that is not sold, a price in the wrong currency, a title
    over Etsy's limit. Those are what the editor shows inline against the
    field that caused them, and they still refuse the write.
    """
    with pytest.raises(ValidationError) as exc:
        Listing.model_validate({**BASE, **over}, context={"currency": "NOK"})
    assert expected_in_message in str(exc.value)

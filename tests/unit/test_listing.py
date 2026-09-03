from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etsy_listings.config.listing import Listing, TemplateMediaEntry
from etsy_listings.config.money import Money

BASE: dict[str, object] = {
    "profile": "comfort-colors-1717",
    "design": "../../designs/take-a-hike.png",
    "colors": ["black"],
    "brief": "test brief",
    "prices": {"S": "349 NOK"},
    "media": [{"template": "flat-lay-01", "colour": "black"}],
}


def test_loads_valid_listing(workspace_root: Path) -> None:
    path = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    listing = Listing.load(path, currency="NOK")
    assert listing.profile == "comfort-colors-1717"
    assert listing.resolved_price("black", "XL") == Money.parse("359 NOK")


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


def test_rejects_more_than_ten_media_entries() -> None:
    data = {**BASE, "media": [f"common-media/asset-{i}.png" for i in range(11)]}
    with pytest.raises(ValidationError, match="10-image limit"):
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

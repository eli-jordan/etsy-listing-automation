from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from etsy_listings.config.errors import ConfigLoadError
from etsy_listings.config.money import Money
from etsy_listings.config.pricing_plan import PricingPlan

BASE: dict[str, object] = {
    "profile": "comfort-colors-1717",
    "prices": {"S": "349 NOK", "M": "349 NOK"},
}


def test_loads_valid_pricing_plan(tmp_path: Path) -> None:
    path = tmp_path / "launch-low.yaml"
    path.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    plan = PricingPlan.load(path, currency="NOK")
    assert plan.profile == "comfort-colors-1717"
    assert plan.prices["S"] == Money.parse("349 NOK")


def test_rejects_bare_number_price_naming_the_field() -> None:
    data = {**BASE, "prices": {"S": 349}}
    with pytest.raises(ValidationError) as exc_info:
        PricingPlan.model_validate(data, context={"currency": "NOK"})
    message = str(exc_info.value)
    assert "prices" in message
    assert "S" in message


def test_rejects_currency_mismatch_in_prices() -> None:
    data = {**BASE, "prices": {"S": "349 USD"}}
    with pytest.raises(ValidationError) as exc_info:
        PricingPlan.model_validate(data, context={"currency": "NOK"})
    message = str(exc_info.value)
    assert "prices.S" in message
    assert "USD" in message
    assert "NOK" in message


def test_rejects_currency_mismatch_in_price_overrides() -> None:
    data = {**BASE, "price_overrides": {"ice-blue": {"XXL": "379 USD"}}}
    with pytest.raises(ValidationError) as exc_info:
        PricingPlan.model_validate(data, context={"currency": "NOK"})
    assert "price_overrides.ice-blue.XXL" in str(exc_info.value)


def test_load_missing_file_raises_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match="not found"):
        PricingPlan.load(tmp_path / "missing.yaml", currency="NOK")


def test_load_wraps_validation_error_with_path(tmp_path: Path) -> None:
    bad_path = tmp_path / "plan.yaml"
    bad_path.write_text(yaml.safe_dump({**BASE, "prices": {"S": 349}}), encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc_info:
        PricingPlan.load(bad_path, currency="NOK")
    assert str(bad_path) in str(exc_info.value)


# --- resolved_price: override > flat > None (Listing.resolved_price's fallback tier) ---


def test_resolved_price_returns_the_flat_table_entry() -> None:
    plan = PricingPlan.model_validate(BASE, context={"currency": "NOK"})
    assert plan.resolved_price("black", "S") == Money.parse("349 NOK")


def test_resolved_price_prefers_a_colour_override() -> None:
    data = {**BASE, "price_overrides": {"ice-blue": {"S": "399 NOK"}}}
    plan = PricingPlan.model_validate(data, context={"currency": "NOK"})
    assert plan.resolved_price("ice-blue", "S") == Money.parse("399 NOK")
    assert plan.resolved_price("black", "S") == Money.parse("349 NOK")


def test_resolved_price_returns_none_when_the_size_is_not_covered() -> None:
    plan = PricingPlan.model_validate(BASE, context={"currency": "NOK"})
    assert plan.resolved_price("black", "XXXL") is None

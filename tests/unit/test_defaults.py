from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.config.defaults import (
    Defaults,
    EtsyDefaults,
    EtsyListingDefaults,
    MissingDefaultError,
    PrintifyDefaults,
)
from etsy_listings.config.errors import ConfigLoadError

MINIMAL: dict[str, object] = {"etsy": {"shop_id": 12345678, "currency": "NOK"}}


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "shop.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_loads_without_a_listing_defaults_block(tmp_path: Path) -> None:
    """A workspace must be usable before the Etsy phase, and every field
    Phase 3 needs has a sensible default (PRD 52 for who_made)."""
    defaults = Defaults.load(_write(tmp_path, MINIMAL))
    assert defaults.etsy.listing_defaults.who_made == "someone_else"
    assert defaults.etsy.listing_defaults.when_made == "made_to_order"
    assert defaults.etsy.listing_defaults.is_supply is False
    assert defaults.etsy.listing_defaults.renewal == "manual"
    assert defaults.etsy.listing_defaults.shipping_profile is None
    assert defaults.etsy.listing_defaults.return_policy is None
    assert defaults.etsy.listing_defaults.production_partner is None


def test_listing_defaults_load_when_set(tmp_path: Path) -> None:
    data = {
        **MINIMAL,
        "etsy": {
            **MINIMAL["etsy"],  # type: ignore[dict-item]
            "listing_defaults": {
                "who_made": "someone_else",
                "when_made": "made_to_order",
                "is_supply": False,
                "renewal": "auto",
                "shipping_profile": "NOK standard tee",
                "return_policy": {
                    "accepts_returns": True,
                    "accepts_exchanges": True,
                    "within_days": 30,
                },
                "production_partner": "The Print Provider",
            },
        },
    }
    defaults = Defaults.load(_write(tmp_path, data))

    listing_defaults = defaults.etsy.listing_defaults
    assert listing_defaults.renewal == "auto"
    assert listing_defaults.shipping_profile == "NOK standard tee"
    assert listing_defaults.production_partner == "The Print Provider"
    assert listing_defaults.return_policy is not None
    assert listing_defaults.return_policy.within_days == 30


def test_no_shop_section_or_return_policy_id_live_in_shop_yaml_anymore() -> None:
    """A shop-wide section default would be right for the first listing and
    wrong from the second onwards; a return policy is now addressed by its
    terms (PRD 59), not an id."""
    assert "shop_section_id" not in EtsyDefaults.model_fields
    assert "return_policy_id" not in EtsyDefaults.model_fields
    assert not hasattr(EtsyDefaults, "require_shop_section_id")
    assert not hasattr(EtsyDefaults, "require_return_policy_id")


def test_the_etsy_shop_id_is_deferrable(tmp_path: Path) -> None:
    """`setup` must be runnable before an Etsy shop exists at all."""
    data = {"etsy": {"currency": "NOK"}}
    defaults = Defaults.load(_write(tmp_path, data))
    assert defaults.etsy.shop_id is None


def test_requiring_an_unset_etsy_shop_id_says_where_to_find_it() -> None:
    etsy = EtsyDefaults.model_validate({"currency": "NOK"})
    with pytest.raises(MissingDefaultError) as exc_info:
        etsy.require_shop_id()
    assert "etsy.shop_id" in str(exc_info.value)


def test_the_printify_shop_id_loads(tmp_path: Path) -> None:
    data = {**MINIMAL, "printify": {"shop_id": 28819281}}
    defaults = Defaults.load(_write(tmp_path, data))
    assert defaults.printify.require_shop_id() == 28819281


def test_the_printify_block_may_be_absent(tmp_path: Path) -> None:
    defaults = Defaults.load(_write(tmp_path, MINIMAL))
    assert defaults.printify.shop_id is None


def test_requiring_an_unset_printify_shop_id_names_setup(tmp_path: Path) -> None:
    defaults = Defaults.load(_write(tmp_path, MINIMAL))
    with pytest.raises(MissingDefaultError) as exc_info:
        defaults.printify.require_shop_id()

    message = str(exc_info.value)
    assert "printify.shop_id" in message
    assert "shop.yaml" in message
    assert "setup" in message


def test_unknown_field_is_still_rejected(tmp_path: Path) -> None:
    data = {**MINIMAL, "etsy": {**MINIMAL["etsy"], "shop_sektion_id": 44}}  # type: ignore[dict-item]
    with pytest.raises(ConfigLoadError, match="shop_sektion_id"):
        Defaults.load(_write(tmp_path, data))


def test_unknown_listing_defaults_field_is_rejected(tmp_path: Path) -> None:
    data = {
        **MINIMAL,
        "etsy": {**MINIMAL["etsy"], "listing_defaults": {"who_maed": "someone_else"}},  # type: ignore[dict-item]
    }
    with pytest.raises(ConfigLoadError, match="who_maed"):
        Defaults.load(_write(tmp_path, data))


def test_unknown_printify_field_is_rejected(tmp_path: Path) -> None:
    data = {**MINIMAL, "printify": {"shop_idd": 1}}
    with pytest.raises(ConfigLoadError, match="shop_idd"):
        Defaults.load(_write(tmp_path, data))


def test_printify_defaults_default_to_empty() -> None:
    assert PrintifyDefaults().shop_id is None


def test_listing_defaults_default_to_the_pod_shape() -> None:
    assert EtsyListingDefaults().who_made == "someone_else"


def test_missing_file_is_an_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match="not found"):
        Defaults.load(tmp_path / "nope.yaml")


# ------------------------------------------------------- keys that have moved


def test_a_top_level_currency_says_where_it_went(tmp_path: Path) -> None:
    stale = {**MINIMAL, "currency": "NOK"}

    with pytest.raises(ConfigLoadError) as caught:
        Defaults.load(_write(tmp_path, stale))

    assert "etsy.currency" in str(caught.value)
    assert "setup" in str(caught.value)


def test_a_top_level_print_provider_says_where_it_went(tmp_path: Path) -> None:
    stale = {**MINIMAL, "preferred_print_provider": "Monster Digital"}

    with pytest.raises(ConfigLoadError) as caught:
        Defaults.load(_write(tmp_path, stale))

    assert "printify.preferred_print_provider" in str(caught.value)


def test_both_moved_keys_are_reported_together(tmp_path: Path) -> None:
    stale = {**MINIMAL, "currency": "NOK", "preferred_print_provider": "Monster Digital"}

    with pytest.raises(ConfigLoadError) as caught:
        Defaults.load(_write(tmp_path, stale))

    assert "etsy.currency" in str(caught.value)
    assert "printify.preferred_print_provider" in str(caught.value)


def test_the_shop_names_load_beside_the_ids(tmp_path: Path) -> None:
    document = {
        "printify": {"shop_name": "My new store", "shop_id": 28819281},
        "etsy": {**MINIMAL["etsy"], "shop_name": "TakeAHikeTees"},  # type: ignore[dict-item]
    }

    defaults = Defaults.load(_write(tmp_path, document))

    assert defaults.printify.shop_name == "My new store"
    assert defaults.etsy.shop_name == "TakeAHikeTees"
    assert defaults.etsy.currency == "NOK"

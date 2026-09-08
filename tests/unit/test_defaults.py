from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from etsy_listings.config.defaults import (
    Defaults,
    EtsyDefaults,
    MissingDefaultError,
    PrintifyDefaults,
)
from etsy_listings.config.errors import ConfigLoadError

MINIMAL: dict[str, object] = {
    "etsy": {
        "shop_id": 12345678,
        "who_made": "i_did",
        "when_made": "made_to_order",
        "is_supply": False,
    },
    "currency": "NOK",
}


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "shop.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_loads_without_the_phase_3_etsy_ids(tmp_path: Path) -> None:
    """A workspace must be usable before the Etsy phase: those ids come back
    *from* the Etsy API, so requiring them at load time would demand values
    that cannot be obtained yet."""
    defaults = Defaults.load(_write(tmp_path, MINIMAL))
    assert defaults.etsy.shop_section_id is None
    assert defaults.etsy.return_policy_id is None


def test_loads_with_the_ids_when_they_are_known(tmp_path: Path) -> None:
    data = {**MINIMAL, "etsy": {**MINIMAL["etsy"], "shop_section_id": 44, "return_policy_id": 55}}  # type: ignore[dict-item]
    defaults = Defaults.load(_write(tmp_path, data))
    assert defaults.etsy.require_shop_section_id() == 44
    assert defaults.etsy.require_return_policy_id() == 55


def test_the_etsy_shop_id_is_deferrable_too(tmp_path: Path) -> None:
    """It was required at load until Phase 2, on the reasoning that it is a
    defining property of the workspace. It is not one yet: a Phase 2 workspace
    creates Printify products and never speaks to Etsy, and `setup` must be
    runnable before an Etsy shop exists at all -- which for this project is the
    actual situation. Demanding it earned one placeholder id that looks real
    enough to be published later."""
    data = {**MINIMAL, "etsy": {k: v for k, v in MINIMAL["etsy"].items() if k != "shop_id"}}  # type: ignore[union-attr]
    defaults = Defaults.load(_write(tmp_path, data))
    assert defaults.etsy.shop_id is None


def test_requiring_an_unset_etsy_shop_id_says_where_to_find_it() -> None:
    etsy = EtsyDefaults.model_validate(
        {k: v for k, v in MINIMAL["etsy"].items() if k != "shop_id"}  # type: ignore[union-attr]
    )
    with pytest.raises(MissingDefaultError) as exc_info:
        etsy.require_shop_id()
    assert "etsy.shop_id" in str(exc_info.value)


def test_the_printify_shop_id_loads(tmp_path: Path) -> None:
    data = {**MINIMAL, "printify": {"shop_id": 28819281}}
    defaults = Defaults.load(_write(tmp_path, data))
    assert defaults.printify.require_shop_id() == 28819281


def test_the_printify_block_may_be_absent(tmp_path: Path) -> None:
    """Every workspace written before Phase 2 has no `printify:` block, and a
    workspace that only renders mockups still does not need one."""
    defaults = Defaults.load(_write(tmp_path, MINIMAL))
    assert defaults.printify.shop_id is None


def test_requiring_an_unset_printify_shop_id_names_setup(tmp_path: Path) -> None:
    """The fix is a command, not a page to go and read: `setup` discovers the
    id from the token rather than making anyone find it in a URL (PRD 42)."""
    defaults = Defaults.load(_write(tmp_path, MINIMAL))
    with pytest.raises(MissingDefaultError) as exc_info:
        defaults.printify.require_shop_id()

    message = str(exc_info.value)
    assert "printify.shop_id" in message
    assert "shop.yaml" in message
    assert "setup" in message


@pytest.mark.parametrize(
    ("accessor", "field"),
    [
        ("require_shop_section_id", "shop_section_id"),
        ("require_return_policy_id", "return_policy_id"),
    ],
)
def test_requiring_an_unset_id_names_the_field_and_how_to_get_it(accessor: str, field: str) -> None:
    etsy = EtsyDefaults.model_validate(MINIMAL["etsy"])
    with pytest.raises(MissingDefaultError) as exc_info:
        getattr(etsy, accessor)()

    message = str(exc_info.value)
    assert f"etsy.{field}" in message
    assert "shop.yaml" in message
    assert "Etsy" in message  # says where the value comes from


def test_unknown_field_is_still_rejected(tmp_path: Path) -> None:
    data = {**MINIMAL, "etsy": {**MINIMAL["etsy"], "shop_sektion_id": 44}}  # type: ignore[dict-item]
    with pytest.raises(ConfigLoadError, match="shop_sektion_id"):
        Defaults.load(_write(tmp_path, data))


def test_unknown_printify_field_is_rejected(tmp_path: Path) -> None:
    data = {**MINIMAL, "printify": {"shop_idd": 1}}
    with pytest.raises(ConfigLoadError, match="shop_idd"):
        Defaults.load(_write(tmp_path, data))


def test_printify_defaults_default_to_empty() -> None:
    assert PrintifyDefaults().shop_id is None


def test_missing_file_is_an_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match="not found"):
        Defaults.load(tmp_path / "nope.yaml")

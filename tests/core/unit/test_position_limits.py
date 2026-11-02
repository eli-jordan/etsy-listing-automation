"""Settings defaults and allowed ranges from template positions interactions."""

import pytest
from pydantic import ValidationError

from etsy_listings.core.config.settings import Settings


def test_defaults_and_empty_section() -> None:
    expected = {"scale": {"min": 0.8, "max": 1.1}, "offset": 0.1, "rotation": 15}
    assert Settings().template_positions.model_dump() == expected
    assert (
        Settings.model_validate({"template_positions": None}).template_positions.model_dump()
        == expected
    )


@pytest.mark.parametrize(
    "limits",
    [
        {"scale": {"min": 0.49}},
        {"scale": {"min": 1.01}},
        {"scale": {"max": 0.99}},
        {"scale": {"max": 1.51}},
        {"offset": -0.01},
        {"offset": 0.26},
        {"rotation": -1},
        {"rotation": 31},
        {"offset": float("nan")},
        {"rotation": float("inf")},
        {"unknown": 1},
    ],
)
def test_invalid_limits_refuse(limits: object) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"template_positions": limits})


@pytest.mark.parametrize(
    "limits",
    [
        {"scale": {"min": 0.5, "max": 1.5}, "offset": 0.25, "rotation": 30},
        {"scale": {"min": 1, "max": 1}, "offset": 0, "rotation": 0},
    ],
)
def test_range_endpoints_are_valid(limits: dict[str, object]) -> None:
    assert (
        Settings.model_validate({"template_positions": limits}).template_positions.model_dump()
        == limits
    )

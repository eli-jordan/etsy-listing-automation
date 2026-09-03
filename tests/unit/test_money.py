from __future__ import annotations

from decimal import Decimal

import pytest

from etsy_listings.config.money import Money, MoneyFormatError, require_currency


def test_parses_amount_and_currency() -> None:
    money = Money.parse("349 NOK")
    assert money.amount == Decimal("349")
    assert money.currency == "NOK"


def test_parses_decimal_amount() -> None:
    money = Money.parse("349.50 NOK")
    assert money.amount == Decimal("349.50")


@pytest.mark.parametrize("bare", [349, 349.5])
def test_rejects_bare_number(bare: int | float) -> None:
    with pytest.raises(MoneyFormatError, match="bare number"):
        Money.parse(bare)


def test_rejects_bool() -> None:
    with pytest.raises(MoneyFormatError):
        Money.parse(True)  # noqa: FBT003


@pytest.mark.parametrize(
    "raw",
    ["349", "NOK 349", "349nok", "", "349 nok"],  # lowercase currency rejected
)
def test_rejects_malformed_strings(raw: str) -> None:
    with pytest.raises(MoneyFormatError):
        Money.parse(raw)


def test_require_currency_passes_when_matching() -> None:
    require_currency(Money.parse("349 NOK"), "NOK", "prices.S")


def test_require_currency_rejects_mismatch_with_actionable_message() -> None:
    with pytest.raises(MoneyFormatError) as exc_info:
        require_currency(Money.parse("349 USD"), "NOK", "prices.S")
    message = str(exc_info.value)
    assert "prices.S" in message
    assert "USD" in message
    assert "NOK" in message


def test_equality_and_hash() -> None:
    a = Money.parse("349 NOK")
    b = Money.parse("349 NOK")
    c = Money.parse("350 NOK")
    assert a == b
    assert hash(a) == hash(b)
    assert a != c


def test_str_round_trips_readably() -> None:
    assert str(Money.parse("349 NOK")) == "349 NOK"

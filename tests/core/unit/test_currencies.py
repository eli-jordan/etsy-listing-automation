"""Which of Etsy Payments' currencies the workspace may be switched to.

ADR-0019: a price reaches Printify as ``Money.minor_units``, which assumes two
decimal places. A currency whose ISO 4217 exponent is not 2 would travel 100x
off, so it is listed but never offered.
"""

from __future__ import annotations

from decimal import Decimal

from etsy_listings.core.config.currencies import (
    ETSY_PAYMENTS_CURRENCIES,
    ISO_4217_EXPONENT,
    OFFERED_CURRENCIES,
)
from etsy_listings.core.config.money import Money


def test_every_etsy_currency_has_a_known_exponent() -> None:
    assert len(ETSY_PAYMENTS_CURRENCIES) == 22
    assert set(ISO_4217_EXPONENT) == set(ETSY_PAYMENTS_CURRENCIES)


def test_only_two_decimal_currencies_are_offered() -> None:
    assert "VND" not in OFFERED_CURRENCIES
    assert set(OFFERED_CURRENCIES) == {
        code for code, exponent in ISO_4217_EXPONENT.items() if exponent == 2
    }
    assert list(OFFERED_CURRENCIES) == [c for c in ETSY_PAYMENTS_CURRENCIES if c != "VND"]


def test_an_offered_currency_round_trips_through_minor_units() -> None:
    for code in OFFERED_CURRENCIES:
        assert Money(Decimal("24.99"), code).minor_units == 2499

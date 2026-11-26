"""The currencies a workspace may be configured in: Etsy Payments' 22, checked on
2026-10-30 against
https://help.etsy.com/hc/en-us/articles/360000337767-Currencies-Supported-for-Etsy-Payments.

Only :data:`OFFERED_CURRENCIES` are offered, because Printify is sent
``Money.minor_units``, the amount times 100, which is wrong for a currency
without two decimal places."""

from __future__ import annotations

ETSY_PAYMENTS_CURRENCIES: dict[str, str] = {
    "USD": "US dollar",
    "AUD": "Australian dollar",
    "CAD": "Canadian dollar",
    "CNY": "Chinese yuan",
    "DKK": "Danish krone",
    "EUR": "Euro",
    "GBP": "British pound",
    "HKD": "Hong Kong dollar",
    "IDR": "Indonesian rupiah",
    "ILS": "Israeli shekel",
    "MAD": "Moroccan dirham",
    "MXN": "Mexican peso",
    "MYR": "Malaysian ringgit",
    "NOK": "Norwegian krone",
    "NZD": "New Zealand dollar",
    "PHP": "Philippine peso",
    "SEK": "Swedish krona",
    "SGD": "Singapore dollar",
    "CHF": "Swiss franc",
    "TRY": "Turkish lira",
    "VND": "Vietnamese dong",
    "ZAR": "South African rand",
}
"""Code to English name, in the order the Admin page offers them."""

_TWO_DECIMALS = 2

ISO_4217_EXPONENT: dict[str, int] = dict.fromkeys(ETSY_PAYMENTS_CURRENCIES, _TWO_DECIMALS) | {
    "VND": 0
}
"""Each currency's minor-unit exponent, from the ISO 4217 list (SIX, the
maintenance agency; checked 2026-10-30). Every Etsy Payments currency has two
decimals except the Vietnamese dong, which has none. IDR is listed with two by
ISO 4217 even though cash prices are rarely written with them."""

OFFERED_CURRENCIES: dict[str, str] = {
    code: name
    for code, name in ETSY_PAYMENTS_CURRENCIES.items()
    if ISO_4217_EXPONENT[code] == _TWO_DECIMALS
}
"""What the Admin page offers and its save accepts: the two-decimal currencies
``Money.minor_units`` serialises correctly (ADR-0019). Etsy lists 22; 21 are
offered."""

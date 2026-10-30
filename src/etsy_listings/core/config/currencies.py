"""The currencies a workspace may be configured in: Etsy Payments' list.

Checked 2026-10-30 against
https://help.etsy.com/hc/en-us/articles/360000337767-Currencies-Supported-for-Etsy-Payments
(22 currencies; the Admin prototype's list matched it). A shop selling in any
other currency cannot take Etsy Payments, so the Admin page offers only these.
``shop.yaml`` itself is not restricted: ADR-0006's explicit-currency rule is
what every price is checked against, whatever the file names.
"""

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

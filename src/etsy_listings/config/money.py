"""Money type: explicit-currency prices only.

PRD 24: every price carries an explicit currency (``349 NOK``); bare numbers and
mismatched currencies are rejected. A bare YAML number (``349``) is valid YAML but
must fail validation here, so the parser only ever accepts the ``"<amount>
<CURRENCY>"`` string form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

_MONEY_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s+([A-Z]{3})\s*$")


class MoneyFormatError(ValueError):
    """Raised when a price is not the required ``"<amount> <CURRENCY>"`` string."""


@dataclass(frozen=True, slots=True)
class Money:
    """An amount paired with its ISO-4217-ish currency code.

    Immutable. The only way to construct one from untrusted input is
    :meth:`parse`, which is also wired in as this type's pydantic validator so it
    applies wherever ``Money`` is used as a field annotation.
    """

    amount: Decimal
    currency: str

    @classmethod
    def parse(cls, raw: Any) -> Money:  # noqa: ANN401 - accepts arbitrary YAML scalars
        if isinstance(raw, Money):
            return raw
        if isinstance(raw, bool) or not isinstance(raw, str | int | float):
            raise MoneyFormatError(
                f"price must be written as '<amount> <CURRENCY>' (e.g. '349 NOK'); got {raw!r}"
            )
        if isinstance(raw, int | float):
            raise MoneyFormatError(
                f"price {raw!r} is a bare number with no currency; write it as "
                f"'{raw} <CURRENCY>' (e.g. '{raw} NOK')"
            )
        match = _MONEY_RE.match(raw)
        if match is None:
            raise MoneyFormatError(
                f"price {raw!r} is not in the form '<amount> <CURRENCY>' " f"(e.g. '349 NOK')"
            )
        amount_str, currency = match.groups()
        try:
            amount = Decimal(amount_str)
        except InvalidOperation as exc:
            raise MoneyFormatError(f"price {raw!r} has an unparseable amount") from exc
        return cls(amount, currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls.parse,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )


def require_currency(money: Money, expected: str, field: str) -> None:
    """Raise an actionable error if ``money`` is not denominated in ``expected``.

    Cross-field validation (a listing's prices against the workspace's
    ``defaults.yaml`` currency) can't live inside :class:`Money` itself, since a
    bare ``Money`` has no notion of what currency the shop expects.
    """
    if money.currency != expected:
        raise MoneyFormatError(
            f"{field}: price is in {money.currency}, but this workspace's "
            f"currency is {expected} (set in defaults.yaml); every price must be "
            f"written in {expected}"
        )

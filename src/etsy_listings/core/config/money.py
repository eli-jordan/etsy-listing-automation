from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

_MONEY_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s+([A-Z]{3})\s*$")


class MoneyFormatError(ValueError): ...


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    @classmethod
    def parse(cls, raw: object) -> Money:
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
                f"price {raw!r} is not in the form '<amount> <CURRENCY>' (e.g. '349 NOK')"
            )
        amount_str, currency = match.groups()
        try:
            amount = Decimal(amount_str)
        except InvalidOperation as exc:
            raise MoneyFormatError(f"price {raw!r} has an unparseable amount") from exc
        return cls(amount, currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    @property
    def minor_units(self) -> int:
        """The amount as an integer number of minor units -- ``349 NOK`` is
        ``34900``. Rounded half-up rather than truncated: banker's rounding on
        a price is a surprise, and truncation loses a øre on every odd amount.
        """
        return int((self.amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, _source_type: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls.parse,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # pydantic derives no JSON Schema from a plain-function core schema.
        return {"type": "string", "examples": ["349 NOK"]}


def require_currency(money: Money, expected: str, field: str) -> None:
    if money.currency != expected:
        raise MoneyFormatError(
            f"{field}: price is in {money.currency}, but this workspace's "
            f"currency is {expected} (set in shop.yaml); every price must be "
            f"written in {expected}"
        )

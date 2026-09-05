"""Contract layer for the one-off, uncached FX-rate fetch used by `new`'s
pricing-plan wizard -- payload shape and fail-soft behaviour, driven through
real ``httpx`` with a mock transport."""

from __future__ import annotations

from decimal import Decimal

import httpx

from etsy_listings.newcmd.fx_rate import fetch_usd_to

FRANKFURTER_PAYLOAD = {"amount": 1.0, "base": "USD", "date": "2026-01-01", "rates": {"NOK": 10.5}}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_request_asks_for_usd_to_the_target_currency() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=FRANKFURTER_PAYLOAD)

    fetch_usd_to("NOK", client=_client(handler))

    assert seen[0].url.params["from"] == "USD"
    assert seen[0].url.params["to"] == "NOK"


def test_decodes_the_rate_as_a_decimal() -> None:
    rate = fetch_usd_to(
        "NOK", client=_client(lambda request: httpx.Response(200, json=FRANKFURTER_PAYLOAD))
    )
    assert rate is not None
    assert rate.rate == Decimal("10.5")
    assert rate.source == "frankfurter.app"


def test_a_non_200_response_returns_none_not_raises() -> None:
    rate = fetch_usd_to(
        "NOK", client=_client(lambda request: httpx.Response(503, text="unavailable"))
    )
    assert rate is None


def test_malformed_json_returns_none_not_raises() -> None:
    rate = fetch_usd_to("NOK", client=_client(lambda request: httpx.Response(200, text="not json")))
    assert rate is None


def test_a_currency_missing_from_the_response_returns_none_not_raises() -> None:
    payload = {"amount": 1.0, "base": "USD", "date": "2026-01-01", "rates": {}}
    rate = fetch_usd_to("NOK", client=_client(lambda request: httpx.Response(200, json=payload)))
    assert rate is None


def test_a_transport_error_returns_none_not_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert fetch_usd_to("NOK", client=_client(handler)) is None

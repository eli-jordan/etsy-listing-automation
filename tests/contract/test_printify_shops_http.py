"""Contract layer for the shop-scoped Printify client: payload shape, auth,
and error decoding, through real ``httpx`` with a mock transport.

Distinct from ``test_catalog_http.py`` because the *protocols* are distinct:
``CatalogClient`` is read-only and shop-agnostic, ``PrintifyClient`` is
shop-scoped and writes. They share a transport, not a surface. The transcripts
below are the ones the ``-m e2e`` layer re-takes against the live API.

Every payload here is transcribed from a real response recorded on
2026-09-08 -- see docs/api-findings.md. A contract fixture that is not a
transcript is worse than no contract test.
"""

from __future__ import annotations

import httpx
import pytest

from etsy_listings.clients.printify import (
    HttpPrintifyClient,
    PrintifyApiError,
    PrintifyAuthError,
)
from etsy_listings.clients.retry import RetryPolicy

from tests.support.http import always, transport

SHOPS_PAYLOAD = [
    {"id": 28819281, "title": "My new store", "sales_channel": "disconnected"},
]
"""What `GET /v1/shops.json` returns, verbatim: three fields and nothing
else -- no currency, no settings (docs/api-findings.md)."""

ERROR_PAYLOAD = {
    "status": "error",
    "code": 8251,
    "message": "Validation failed.",
    "errors": {
        "reason": (
            "Variants do not match selected blueprint and print provider. Please make "
            "sure that all product variants are present in the "
            "`print_areas.*.variant_ids` field"
        ),
        "code": 8251,
    },
}
"""Every failure this API produces has this shape. `errors.reason` is a human
sentence naming the field, and is the only part worth showing a user."""


def _client(handler, token: str = "test-token") -> HttpPrintifyClient:
    return HttpPrintifyClient(transport(handler, token=token))


def test_shops_carries_the_bearer_token_and_hits_the_documented_path() -> None:
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("Authorization")))
        return httpx.Response(200, json=SHOPS_PAYLOAD)

    _client(handler).shops()

    assert seen == [("/v1/shops.json", "Bearer test-token")]


def test_shops_decodes_the_documented_payload_shape() -> None:
    shops = _client(lambda _: httpx.Response(200, json=SHOPS_PAYLOAD)).shops()

    assert [(s.id, s.title, s.sales_channel) for s in shops] == [
        (28819281, "My new store", "disconnected")
    ]


def test_a_shop_without_a_sales_channel_key_is_not_fatal() -> None:
    """Printify omits keys rather than nulling them (`external` on a product
    is absent, not null), so nothing may assume a field is present."""
    shops = _client(lambda _: httpx.Response(200, json=[{"id": 1, "title": "s"}])).shops()

    assert shops[0].sales_channel is None


def test_fields_printify_adds_later_are_ignored_not_fatal() -> None:
    payload = [{**SHOPS_PAYLOAD[0], "some_new_field": "surprise"}]
    shops = _client(lambda _: httpx.Response(200, json=payload)).shops()

    assert shops[0].id == 28819281


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_become_an_actionable_error(status: int) -> None:
    """Named separately from any other failure because the fix is a specific
    human action, not a retry."""
    with pytest.raises(PrintifyAuthError) as exc_info:
        _client(lambda _: httpx.Response(status, json={"message": "Unauthenticated."})).shops()

    message = str(exc_info.value)
    assert "PRINTIFY_API_TOKEN" in message
    assert "printify.com" in message


def test_an_api_error_surfaces_the_reason_verbatim() -> None:
    """`errors.reason` is the only part of the envelope that says what to fix,
    so it is what the user must see -- not `code: 8251`."""
    with pytest.raises(PrintifyApiError) as exc_info:
        _client(lambda _: httpx.Response(400, json=ERROR_PAYLOAD)).shops()

    error = exc_info.value
    assert error.code == 8251
    assert "print_areas.*.variant_ids" in str(error)


def test_an_error_without_the_envelope_still_reports_something_useful() -> None:
    """A 500 from a proxy is not JSON at all. The client must not crash while
    decoding the thing that tells the user what went wrong."""
    with pytest.raises(PrintifyApiError) as exc_info:
        _client(lambda _: httpx.Response(502, text="<html>Bad Gateway</html>")).shops()

    assert "502" in str(exc_info.value)


def test_the_token_is_resolved_lazily() -> None:
    """`plan` builds clients it may never call, and a workspace with no `.env`
    must not fail at construction -- the same rule the catalog client follows."""
    calls: list[str] = []

    def token() -> str:
        calls.append("resolved")
        return "late-token"

    client = HttpPrintifyClient(
        transport(always(httpx.Response(200, json=SHOPS_PAYLOAD)), token=token)
    )
    assert calls == []

    client.shops()
    assert calls == ["resolved"]


def test_an_envelope_without_a_reason_falls_back_to_the_message() -> None:
    """Not every refusal carries `errors.reason` -- an auth-shaped body is
    just `{"message": ...}`. Showing the raw JSON instead would bury the one
    sentence that says what happened."""
    body = {"status": "error", "code": 8254, "message": "Shop is not connected"}

    with pytest.raises(PrintifyApiError) as exc_info:
        _client(lambda _: httpx.Response(400, json=body)).shops()

    assert exc_info.value.code == 8254
    assert "Shop is not connected" in str(exc_info.value)


def test_an_envelope_with_neither_falls_back_to_the_body_text() -> None:
    """A dict that says nothing recognisable is still better shown than
    swallowed: whatever it holds is the only evidence there is."""
    with pytest.raises(PrintifyApiError) as exc_info:
        _client(lambda _: httpx.Response(400, json={"unexpected": "shape"})).shops()

    error = exc_info.value
    assert error.code is None
    assert "unexpected" in str(error)


def test_a_json_error_body_that_is_not_an_object_is_survivable() -> None:
    with pytest.raises(PrintifyApiError) as exc_info:
        _client(lambda _: httpx.Response(400, json=["nope"])).shops()

    assert "nope" in str(exc_info.value)


def test_an_empty_error_body_still_names_the_status() -> None:
    with pytest.raises(PrintifyApiError) as exc_info:
        _client(lambda _: httpx.Response(500, text="")).shops()

    assert "500" in str(exc_info.value)
    assert "no response body" in str(exc_info.value)


# ------------------------------------------------------------------- retries

# A21. The policy itself is unit-tested in tests/unit/test_retry.py; what
# these pin is that the client actually goes through it, and that the caller
# still sees a real decoded error when the retries run out.


def _retrying_client(handler, policy: RetryPolicy) -> HttpPrintifyClient:
    return HttpPrintifyClient(transport(handler, policy=policy))


INSTANT = RetryPolicy(attempts=3, base_delay=0.0, max_delay=0.0, jitter=0.0)


def test_a_rate_limited_read_is_retried_and_succeeds() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=SHOPS_PAYLOAD),
        ]
    )

    shops = _retrying_client(lambda _: next(responses), INSTANT).shops()

    assert shops[0].id == 28819281


def test_retries_that_run_out_surface_the_real_error_not_a_wrapper() -> None:
    with pytest.raises(PrintifyApiError) as exc_info:
        _retrying_client(
            lambda _: httpx.Response(503, json={"message": "Service Unavailable"}), INSTANT
        ).shops()

    assert "Service Unavailable" in str(exc_info.value)


def test_a_rejected_token_is_not_retried() -> None:
    """401 is a verdict. Retrying it three times just delays the message that
    says what to fix."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"message": "Unauthenticated."})

    with pytest.raises(PrintifyAuthError):
        _retrying_client(handler, INSTANT).shops()

    assert len(calls) == 1

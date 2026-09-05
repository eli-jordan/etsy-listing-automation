"""Contract layer for the undocumented Printify per-variant cost endpoint --
payload shape and request shape, driven through real ``httpx`` with a mock
transport, the same reason ``test_catalog_http.py`` exists for the documented
catalog. This endpoint has no auth and no docs, so every test here is really
about confirming the fail-soft policy: nothing this module does should ever
raise out of ``fetch_variant_costs``.
"""

from __future__ import annotations

import httpx

from etsy_listings.newcmd.unofficial_variant_costs import fetch_variant_costs

REAL_SHAPED_PAYLOAD = {
    "total": 1,
    "data": [
        {
            "id": 148324,
            "options": [4802, 14],
            "costs": [{"result": 1304, "result_subscription": 1127}],
        }
    ],
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_request_shape_and_decoration_method_param() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=REAL_SHAPED_PAYLOAD)

    fetch_variant_costs(706, 29, decoration_method="dtg", client=_client(handler))

    assert len(seen) == 1
    assert seen[0].url.path.endswith("/blueprints/706/print-providers/29/variants")
    assert seen[0].url.params["decoration_method"] == "dtg"


def test_no_authorization_header_is_sent() -> None:
    """Unlike the documented catalog API, this endpoint takes no token --
    confirming that so a future change doesn't accidentally start leaking one."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json=REAL_SHAPED_PAYLOAD)

    fetch_variant_costs(706, 29, client=_client(handler))
    assert seen == [None]


def test_decodes_the_real_captured_shape() -> None:
    result = fetch_variant_costs(
        706, 29, client=_client(lambda request: httpx.Response(200, json=REAL_SHAPED_PAYLOAD))
    )
    assert result == {148324: 1304}


def test_a_non_200_response_returns_empty_not_raises() -> None:
    result = fetch_variant_costs(
        999, 999, client=_client(lambda request: httpx.Response(400, text="bad request"))
    )
    assert result == {}


def test_malformed_json_returns_empty_not_raises() -> None:
    result = fetch_variant_costs(
        706, 29, client=_client(lambda request: httpx.Response(200, text="not json"))
    )
    assert result == {}


def test_a_transport_error_returns_empty_not_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = fetch_variant_costs(706, 29, client=_client(handler))
    assert result == {}

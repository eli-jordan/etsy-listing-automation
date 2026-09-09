"""Contract layer for Etsy's authentication: what goes on the wire, through
real ``httpx`` with a mock transport.

Two surfaces, and the difference between them is the point. Every API request
carries **both** credentials -- `x-api-key: keystring:shared_secret` and a
bearer -- while the token endpoint carries **neither**, authenticating by
`client_id` in a form body. Getting that backwards fails in a way no offline
test would otherwise catch: a token request with an `Authorization` header
still works, right up until the token it is carrying expires.

Payloads are transcribed from Etsy's authentication guide and quick-start
tutorial (docs/prd.md 49, 50); the `-m e2e` layer is what re-takes them
against the live API.
"""

from __future__ import annotations

import httpx
import pytest

from etsy_listings.clients.etsy import oauth
from etsy_listings.clients.etsy.tokens import EtsyAuthError
from etsy_listings.clients.etsy.transport import PING_PATH, EtsyApiError

from tests.support.http import etsy_oauth_client, etsy_transport

TOKEN_PAYLOAD = {
    "access_token": "12345678.O1zLuwveeKjpIqCQFfmR-PaMMpBmagH6DljRAkK9qt05OtRKiANJOyZ",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "12345678.JNGIJtvLmwfDMhlYoOJl8aLR1BWottyHC6yhNcET-eC7RogSR5e",
    "scope": "listings_r listings_w shops_r",
}


# ------------------------------------------------------------------ the API


def test_every_request_carries_the_colon_joined_app_key() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["x-api-key"])
        return httpx.Response(200, json={"application_id": 1234})

    etsy_transport(handler).ping()

    assert seen == ["test-keystring:test-secret"]


def test_a_scoped_request_carries_the_bearer_as_well() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"application_id": 1234})

    etsy_transport(handler).get("/v3/application/shops/1/sections")

    assert seen["authorization"] == "Bearer 12345678.test-access"
    assert seen["x-api-key"] == "test-keystring:test-secret"


def test_ping_needs_no_bearer_at_all() -> None:
    """The check `auth` makes before a token exists -- so a transport built
    without one must not invent an `Authorization` header."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        assert request.url.path == PING_PATH
        return httpx.Response(200, json={"application_id": 1234})

    assert etsy_transport(handler, bearer=None).ping() == 1234


def test_a_ping_without_an_application_id_is_not_taken_as_success() -> None:
    handler = lambda _: httpx.Response(200, json={"ok": True})  # noqa: E731

    with pytest.raises(EtsyApiError):
        etsy_transport(handler, bearer=None).ping()


def test_a_rejected_app_key_names_the_two_variables_to_fix() -> None:
    """With no bearer in play, a 401 can only be the key pair, and the message
    says so rather than covering both cases vaguely."""
    handler = lambda _: httpx.Response(401, json={"error": "invalid api key"})  # noqa: E731

    with pytest.raises(EtsyAuthError) as caught:
        etsy_transport(handler, bearer=None).ping()

    assert "ETSY_KEYSTRING" in str(caught.value)
    assert "ETSY_SHARED_SECRET" in str(caught.value)


def test_an_etsy_error_envelope_is_decoded_to_its_one_string() -> None:
    """Etsy's error shape is a single `error` string -- no code, no field --
    so the whole value is what a human gets."""
    handler = lambda _: httpx.Response(  # noqa: E731
        400, json={"error": "Listing title contains invalid characters"}
    )

    with pytest.raises(EtsyApiError) as caught:
        etsy_transport(handler).get("/v3/application/listings/1")

    assert caught.value.error == "Listing title contains invalid characters"
    assert caught.value.status_code == 400


def test_a_non_json_failure_still_reports_something_readable() -> None:
    """A 502 from a proxy is HTML. Failing while decoding a failure is the
    worst moment to fail."""
    handler = lambda _: httpx.Response(502, text="<html>Bad Gateway</html>")  # noqa: E731

    with pytest.raises(EtsyApiError) as caught:
        etsy_transport(handler).get("/v3/application/listings/1")

    assert "Bad Gateway" in caught.value.error


# --------------------------------------------------------- the token endpoint


def test_the_code_exchange_posts_a_form_to_the_documented_url() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["type"] = request.headers.get("content-type")
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers.get("authorization")
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json=TOKEN_PAYLOAD)

    etsy_oauth_client(handler).exchange(code="c0de", verifier="v3rifier")

    assert seen["url"] == oauth.TOKEN_URL
    assert seen["type"] == "application/x-www-form-urlencoded"
    body = str(seen["body"])
    assert "grant_type=authorization_code" in body
    assert "client_id=test-keystring" in body
    assert "code=c0de" in body
    assert "code_verifier=v3rifier" in body
    # Neither credential belongs here: the token endpoint authenticates by
    # `client_id` in the body, and sending a stale bearer to it is a failure
    # that only appears once the bearer expires.
    assert seen["auth"] is None
    assert seen["key"] is None


def test_the_exchange_returns_the_parsed_pair() -> None:
    handler = lambda _: httpx.Response(200, json=TOKEN_PAYLOAD)  # noqa: E731

    parsed = etsy_oauth_client(handler).exchange(code="c", verifier="v")

    assert parsed.access_token == TOKEN_PAYLOAD["access_token"]
    assert parsed.refresh_token == TOKEN_PAYLOAD["refresh_token"]
    assert parsed.user_id == 12345678


def test_a_refresh_posts_the_refresh_grant_and_nothing_else() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode())
        return httpx.Response(200, json=TOKEN_PAYLOAD)

    etsy_oauth_client(handler).refresh("12345678.old-refresh")

    body = seen[0]
    assert "grant_type=refresh_token" in body
    assert "refresh_token=12345678.old-refresh" in body
    assert "redirect_uri" not in body
    assert "code_verifier" not in body


def test_a_used_code_comes_back_as_a_grant_failure() -> None:
    """Transcribed from the quick-start tutorial's own error example."""
    handler = lambda _: httpx.Response(  # noqa: E731
        400, json={"error": "invalid_grant", "error_description": "code has been used previously"}
    )

    with pytest.raises(oauth.OAuthError) as caught:
        etsy_oauth_client(handler).exchange(code="c", verifier="v")

    assert caught.value.is_grant_failure
    assert caught.value.description == "code has been used previously"


def test_an_unreadable_body_is_reported_with_its_status() -> None:
    handler = lambda _: httpx.Response(503, text="upstream connect error")  # noqa: E731

    with pytest.raises(oauth.OAuthError) as caught:
        etsy_oauth_client(handler).refresh("r")

    assert caught.value.error == "http_503"
    assert not caught.value.is_grant_failure

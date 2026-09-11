"""Etsy's OAuth flow as strings and payloads -- no socket, no browser.

This is where the flow's rules are pinned: that the challenge really is the
SHA-256 of the verifier, that the registered redirect is sent verbatim, that a
mismatched `state` stops everything, and that a malformed token response is
refused rather than half-read.
"""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from etsy_listings.clients.etsy import oauth

# --------------------------------------------------------------------- PKCE


def test_the_challenge_is_the_sha256_of_the_verifier() -> None:
    pkce = oauth.Pkce.generate()

    digest = hashlib.sha256(pkce.verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    assert pkce.challenge == expected


def test_the_verifier_is_within_the_length_and_alphabet_rfc7636_allows() -> None:
    """43-128 characters from the unreserved set. Etsy rejects the flow rather
    than the verifier, so a bad one surfaces as a consent page that fails."""
    pkce = oauth.Pkce.generate()

    assert 43 <= len(pkce.verifier) <= 128
    assert all(c.isalnum() or c in "-._~" for c in pkce.verifier)


def test_two_flows_do_not_share_a_verifier() -> None:
    assert oauth.Pkce.generate().verifier != oauth.Pkce.generate().verifier


def test_the_verifier_uses_the_injected_entropy() -> None:
    pkce = oauth.Pkce.generate(entropy=lambda n: b"\x00" * n)

    assert pkce.verifier == base64.urlsafe_b64encode(b"\x00" * 32).decode().rstrip("=")


# ------------------------------------------------------------ authorize URL


def test_the_authorize_url_carries_every_parameter_etsy_requires() -> None:
    pkce = oauth.Pkce.generate()

    url = oauth.authorize_url(keystring="key123", pkce=pkce, state="st4te")

    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == oauth.AUTHORIZE_URL
    query = parse_qs(split.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["key123"]
    assert query["redirect_uri"] == [oauth.REDIRECT_URI]
    assert query["state"] == ["st4te"]
    assert query["code_challenge"] == [pkce.challenge]
    assert query["code_challenge_method"] == ["S256"]


def test_scopes_are_space_separated_and_percent_encoded() -> None:
    url = oauth.authorize_url(keystring="k", pkce=oauth.Pkce.generate(), state="s")

    assert f"scope={'%20'.join(oauth.SCOPES)}" in url
    assert parse_qs(urlsplit(url).query)["scope"] == [" ".join(oauth.SCOPES)]


def test_the_registered_scopes_are_the_ones_phase_3_needs() -> None:
    """PRD 50. `listings_d` is deliberately absent: it deletes listings, and
    image delete is covered by `listings_w`."""
    assert set(oauth.SCOPES) == {"listings_r", "listings_w", "shops_r"}
    assert "listings_d" not in oauth.SCOPES


def test_the_redirect_uri_matches_what_is_registered_with_the_app() -> None:
    """Etsy compares this as an exact string -- scheme, port, path, no
    trailing slash -- so changing it means re-registering the app."""
    assert oauth.REDIRECT_URI == "http://localhost:8517/oauth/callback"


# -------------------------------------------------------------------- state


def test_a_matching_state_passes() -> None:
    oauth.check_state(sent="abc", received="abc")


@pytest.mark.parametrize("received", ["different", None, ""])
def test_a_missing_or_different_state_is_refused(received: str | None) -> None:
    with pytest.raises(oauth.OAuthError) as caught:
        oauth.check_state(sent="abc", received=received)

    assert caught.value.error == "state_mismatch"


# --------------------------------------------------------------------- form


def test_the_code_exchange_sends_the_verifier_and_the_same_redirect() -> None:
    form = oauth.authorization_code_form(keystring="k", code="c0de", verifier="v3rifier")

    assert form == {
        "grant_type": "authorization_code",
        "client_id": "k",
        "redirect_uri": oauth.REDIRECT_URI,
        "code": "c0de",
        "code_verifier": "v3rifier",
    }


def test_the_refresh_grant_sends_neither_redirect_nor_verifier() -> None:
    """A refresh carries neither, and sending them is how a working refresh
    starts failing after a callback change."""
    form = oauth.refresh_form(keystring="k", refresh_token="r3fresh")

    assert form == {"grant_type": "refresh_token", "client_id": "k", "refresh_token": "r3fresh"}


# ----------------------------------------------------------- token response

PAYLOAD = {
    "access_token": "12345678.access",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "12345678.refresh",
    "scope": "listings_r listings_w shops_r",
}


def test_a_successful_payload_parses() -> None:
    parsed = oauth.TokenResponse.parse(PAYLOAD)

    assert parsed.access_token == "12345678.access"
    assert parsed.refresh_token == "12345678.refresh"
    assert parsed.expires_in == 3600
    assert parsed.scope == "listings_r listings_w shops_r"


def test_the_user_id_comes_from_the_token_prefix() -> None:
    """The only place the flow yields a user id without a further request."""
    assert oauth.TokenResponse.parse(PAYLOAD).user_id == 12345678


def test_a_token_without_the_documented_prefix_is_refused() -> None:
    parsed = oauth.TokenResponse.parse({**PAYLOAD, "access_token": "no-prefix-here"})

    with pytest.raises(oauth.OAuthError) as caught:
        _ = parsed.user_id
    assert caught.value.error == "unexpected_token_format"


def test_an_error_payload_becomes_an_oauth_error_with_its_description() -> None:
    with pytest.raises(oauth.OAuthError) as caught:
        oauth.TokenResponse.parse(
            {"error": "invalid_grant", "error_description": "code has been used previously"}
        )

    assert caught.value.error == "invalid_grant"
    assert caught.value.description == "code has been used previously"
    assert caught.value.is_grant_failure


def test_only_a_grant_failure_reads_as_one() -> None:
    """The distinction the caller acts on: `invalid_grant` means sign in
    again, everything else means look at the request."""
    assert not oauth.OAuthError("invalid_request").is_grant_failure


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        {"access_token": "12345678.a", "expires_in": 3600},
        {"access_token": "", "refresh_token": "r", "expires_in": 3600},
        {"access_token": "12345678.a", "refresh_token": "r", "expires_in": "soon"},
    ],
)
def test_a_malformed_payload_is_refused_rather_than_half_read(payload: object) -> None:
    with pytest.raises(oauth.OAuthError):
        oauth.TokenResponse.parse(payload)


def test_a_payload_without_scope_parses_as_unknown_scope() -> None:
    """A token-exchange grant documents no `scope`; absent is not malformed."""
    payload = {k: v for k, v in PAYLOAD.items() if k != "scope"}

    assert oauth.TokenResponse.parse(payload).scope == ""
